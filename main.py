# -*- coding: utf-8 -*-
"""DESTIN SONOR — lecteur audio/vidéo Kivy pour Android.

Images du projet : exactement deux fichiers image fournis :
- BG.jpg : seule image affichée comme arrière-plan de l'interface.
- ic_launcher.png : logo réservé à l'icône de l'application (jamais affiché dans l'écran du lecteur).
Aucune pochette d'album ou image décorative n'est ajoutée à l'interface.

Fonctions : bibliothèque locale audio/vidéo, recherche, lecture, pause,
précédent/suivant, volume, modes aléatoire/répétition, avance/recul lorsque
le moteur le permet, lecture vidéo selon codecs, panneau compact de liste,
réglages de texte et verrouillage PIN local.

Limites : la lecture persistante écran verrouillé, les notifications média
Android et l'empreinte digitale nécessitent une intégration Android native.
Ce code source Kivy n'est pas lui-même un APK compilé.
"""

import os
import json
import random
import hashlib
import traceback
from pathlib import Path

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.core.audio import SoundLoader
from kivy.metrics import dp
from kivy.graphics import Color, Rectangle
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.uix.scrollview import ScrollView
from kivy.uix.slider import Slider
from kivy.uix.image import Image
from kivy.uix.video import Video
from kivy.uix.popup import Popup
from kivy.uix.filechooser import FileChooserListView

APP_NAME = "DESTIN SONOR"
BG_DEFAULT_NAME = "BG.jpg"
AUDIO_EXTS = {".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac", ".wma"}
VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".3gp", ".m4v"}
MEDIA_EXTS = AUDIO_EXTS | VIDEO_EXTS
SCAN_DIRS = [
    "/storage/emulated/0/Music",
    "/storage/emulated/0/Download",
    "/storage/emulated/0/Audio",
    "/storage/emulated/0/Movies",
    "/storage/emulated/0/DCIM",
    "/storage/emulated/0/Pictures",
    "/storage/emulated/0/Podcasts",
]
DARK = (0.025, 0.035, 0.06, 1)
ACCENT = (0.08, 0.52, 0.31, 1)
PANEL = (0.09, 0.12, 0.18, 0.95)
WHITE = (0.96, 0.97, 1, 1)
MUTED = (0.68, 0.73, 0.81, 1)


def display_name(path):
    return Path(path).stem.replace("_", " ").replace("-", " ")


def is_video(path):
    return Path(path).suffix.lower() in VIDEO_EXTS


def pin_digest(pin):
    return hashlib.sha256(pin.encode("utf-8")).hexdigest()


class DestinSonorApp(App):
    def build(self):
        self.title = APP_NAME
        Window.clearcolor = DARK
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.settings_file = os.path.join(self.base_dir, "destin_sonor_settings.json")
        self.error_file = os.path.join(self.base_dir, "destin_sonor_erreur.txt")

        self.screen_name = "library"
        # Cherche BG.jpg près du script puis dans les dossiers habituels Android.
        self.default_bg = os.path.join(self.base_dir, BG_DEFAULT_NAME)
        candidates = [
            self.default_bg,
            "/storage/emulated/0/Download/BG.jpg",
            "/storage/emulated/0/Pictures/BG.jpg",
            "/storage/emulated/0/DCIM/BG.jpg",
            "/storage/emulated/0/BG.jpg",
        ]
        self.default_bg = next((p for p in candidates if os.path.isfile(p)), candidates[0])
        # Recherche complémentaire sans tenir compte des majuscules/minuscules du nom.
        if not os.path.isfile(self.default_bg):
            for folder in [self.base_dir, "/storage/emulated/0/Download",
                           "/storage/emulated/0/Pictures", "/storage/emulated/0/DCIM",
                           "/storage/emulated/0"]:
                try:
                    for filename in os.listdir(folder):
                        if filename.lower() == "bg.jpg":
                            found = os.path.join(folder, filename)
                            if os.path.isfile(found):
                                self.default_bg = found
                                break
                    if os.path.isfile(self.default_bg):
                        break
                except (OSError, PermissionError):
                    continue
        self.background_image_path = self.default_bg if os.path.isfile(self.default_bg) else ""
        self.media = []
        self.filtered = []
        self.current_path = None
        self.sound = None
        self.video_widget = None
        self.bg_widget = None
        self.page = None
        self.media_list = None
        self.count_label = None
        self.playlist_panel = None
        self.play_button = None
        self.now_label = None
        self.volume = 0.8
        self.font_size = 16
        self.text_color = list(WHITE)
        self.shuffle = False
        self.repeat = False
        self.audio_only = False
        self.pin_hash = ""
        self.pin_enabled = False
        self.is_unlocked = True
        self._video_finished_event = None
        self._progress_event = None
        self._slider_is_being_dragged = False
        self._last_audio_position = 0.0

        self.load_settings()
        self.root = FloatLayout()
        self.root.bind(size=lambda *_: self.update_bg_size())
        self.scan_media()
        if self.pin_enabled:
            self.is_unlocked = False
            self.show_pin_screen(initial=False)
        else:
            self.show_library()
        # Android 6+ requires runtime media permissions as well as manifest entries.
        Clock.schedule_once(lambda _dt: self.request_media_permissions(), 0.8)
        return self.root

    def request_media_permissions(self):
        try:
            from android.permissions import request_permissions, Permission
            wanted = []
            for name in ("READ_EXTERNAL_STORAGE", "READ_MEDIA_AUDIO", "READ_MEDIA_VIDEO"):
                permission = getattr(Permission, name, None)
                if permission:
                    wanted.append(permission)
            if wanted:
                request_permissions(wanted, self._permissions_result)
        except Exception:
            # Desktop development and Android builds without this bridge can still run.
            pass

    def _permissions_result(self, permissions, grants):
        try:
            if any(bool(granted) for granted in grants):
                Clock.schedule_once(lambda _dt: self.refresh_library(), 0.2)
        except Exception:
            pass

    # ---------- settings and errors ----------
    def log_error(self, details):
        try:
            with open(self.error_file, "a", encoding="utf-8") as f:
                f.write("\n\n--- ERREUR DESTIN SONOR ---\n")
                f.write(details)
        except Exception:
            pass

    def load_settings(self):
        try:
            with open(self.settings_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
        # Toujours utiliser l'unique image de fond fournie avec le projet.
        self.background_image_path = self.default_bg if os.path.isfile(self.default_bg) else ""
        self.volume = max(0.0, min(2.0, float(data.get("volume", 0.8))))
        self.font_size = max(12, min(28, int(data.get("font_size", 16))))
        self.text_color = data.get("text_color", list(WHITE))
        self.shuffle = bool(data.get("shuffle", False))
        self.repeat = bool(data.get("repeat", False))
        self.pin_hash = data.get("pin_hash", "")
        self.pin_enabled = bool(self.pin_hash)

    def save_settings(self):
        data = {
            "volume": self.volume,
            "font_size": self.font_size,
            "text_color": self.text_color,
            "shuffle": self.shuffle,
            "repeat": self.repeat,
            "pin_hash": self.pin_hash,
        }
        try:
            with open(self.settings_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            self.log_error(traceback.format_exc())

    # ---------- interface helpers ----------
    def button(self, text, callback, height=46, color=ACCENT, size=15, fixed_font=False):
        # A-/A+ scales the general interface. Compact playlist controls opt out.
        scale = self.font_size / 16.0
        effective_size = size if fixed_font else max(8, min(36, size * scale))
        b = Button(
            text=text, size_hint_y=None, height=dp(height),
            background_normal="", background_down="", background_color=color,
            color=self.text_color, font_size=f"{effective_size}sp", italic=True
        )
        b.bind(on_release=callback)
        return b

    def label(self, text, size=15, height=32, color=None, bold=False, fixed_font=False):
        scale = self.font_size / 16.0
        effective_size = size if fixed_font else max(8, min(36, size * scale))
        w = Label(
            text=text, size_hint_y=None, height=dp(height),
            color=color or self.text_color, font_size=f"{effective_size}sp",
            bold=bold, italic=True, halign="center", valign="middle"
        )
        w.bind(size=lambda obj, val: setattr(obj, "text_size", val))
        return w

    def clear_root(self):
        # Release an old video widget when changing screens; audio playback is not
        # stopped here so rebuilding the UI does not interrupt the current track.
        if self.video_widget is not None:
            try:
                self.video_widget.state = "stop"
            except Exception:
                pass
        if self._progress_event is not None:
            try:
                self._progress_event.cancel()
            except Exception:
                pass
            self._progress_event = None
        self.root.clear_widgets()
        self.bg_widget = None
        self.video_widget = None
        self.page = BoxLayout(
            orientation="vertical", padding=dp(12), spacing=dp(8),
            size_hint=(1, 1), pos_hint={"x": 0, "y": 0}
        )
        self.root.add_widget(self.page)
        self.add_background()

    def add_background(self):
        """Affiche uniquement BG.jpg derrière l'interface, sans logo superposé."""
        if not self.background_image_path or not os.path.isfile(self.background_image_path):
            return
        try:
            self.bg_widget = Image(
                source=self.background_image_path,
                allow_stretch=True,
                keep_ratio=False,
                opacity=0.78,
                size_hint=(1, 1),
                pos_hint={"x": 0, "y": 0},
            )
            # Le fond doit rester derrière tous les widgets de l'interface.
            self.root.add_widget(self.bg_widget, index=len(self.root.children))
        except Exception:
            self.bg_widget = None

    def update_bg_size(self):
        pass

    def header(self, title, back=False):
        row = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(6))
        if back:
            row.add_widget(self.button("← Retour", self.show_library, 44, PANEL, 13))
        row.add_widget(self.label(title, 19, 44, WHITE, True))
        row.add_widget(self.button("⋮", self.open_menu, 44, PANEL, 22))
        return row

    def message(self, title, text):
        box = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(10))
        lab = Label(text=text, color=WHITE, halign="center", valign="middle")
        lab.bind(size=lambda obj, val: setattr(obj, "text_size", val))
        box.add_widget(lab)
        pop = Popup(title=title, content=box, size_hint=(0.9, 0.42))
        box.add_widget(self.button("OK", lambda *_: pop.dismiss(), 42))
        pop.open()

    # ---------- media library ----------
    def scan_media(self):
        found = set()
        for folder in SCAN_DIRS:
            if not os.path.isdir(folder):
                continue
            for base, dirs, files in os.walk(folder):
                dirs[:] = [d for d in dirs if not d.startswith(".")]
                for filename in files:
                    if Path(filename).suffix.lower() in MEDIA_EXTS:
                        found.add(os.path.join(base, filename))
        self.media = sorted(found, key=lambda p: display_name(p).lower())
        self.filtered = list(self.media)

    def show_library(self, *_):
        """Écran d'accueil : recherche en haut, bibliothèque au centre, commandes en bas."""
        self.screen_name = "library"
        self.clear_root()
        self.page.padding = [dp(10), dp(8), dp(10), dp(8)]
        self.page.spacing = dp(6)

        top = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6))
        top.add_widget(self.label("DESTIN", 21, 42, WHITE, True))
        top.add_widget(self.label("SONOR", 21, 42, ACCENT, True))
        top.add_widget(self.button("⋮", self.open_menu, 42, PANEL, 21))
        self.page.add_widget(top)

        search = TextInput(
            hint_text="Rechercher un son...", multiline=False,
            size_hint_y=None, height=dp(42), background_normal="",
            background_active="", background_color=(0.06, 0.08, 0.12, 0.96),
            foreground_color=self.text_color, hint_text_color=MUTED,
            cursor_color=ACCENT, padding=[dp(10), dp(8), dp(10), dp(6)], font_size="15sp")
        search.bind(text=self.filter_media)
        self.page.add_widget(search)
        self.count_label = self.label("", 11, 22, MUTED)
        self.page.add_widget(self.count_label)

        # Grande liste au centre et réglage du volume sur le côté droit, comme le croquis.
        content = BoxLayout(orientation="horizontal", spacing=dp(6))
        scroll = ScrollView(do_scroll_x=False, size_hint_x=0.84)
        self.media_list = GridLayout(cols=1, spacing=dp(5), size_hint_y=None, padding=[0, dp(2), 0, dp(2)])
        self.media_list.bind(minimum_height=self.media_list.setter("height"))
        scroll.add_widget(self.media_list)
        content.add_widget(scroll)

        # Curseur vertical à déplacement continu : volume de 0 à 200 %.
        volume_col = BoxLayout(orientation="vertical", size_hint_x=0.19, spacing=dp(4), padding=[0, dp(6), 0, dp(6)])
        volume_col.add_widget(self.label("VOL.", 10, 24, MUTED, True, fixed_font=True))
        self.library_volume_label = self.label(f"{int(self.volume * 100)}%", 10, 25, WHITE, True, fixed_font=True)
        volume_col.add_widget(self.library_volume_label)
        self.library_volume_slider = Slider(orientation="vertical", min=0, max=2, value=self.volume,
                                            step=0.01, size_hint=(1, 1))
        self.library_volume_slider.bind(value=self.change_volume)
        volume_col.add_widget(self.library_volume_slider)
        content.add_widget(volume_col)
        self.page.add_widget(content)

        row = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(7))
        row.add_widget(self.button("⟳ Actualiser", self.refresh_library, 44, PANEL, 13))
        row.add_widget(self.button("▶ Lecteur", self.open_first, 44, ACCENT, 14))
        self.page.add_widget(row)
        self.render_media()

    def adjust_volume(self, delta):
        self.change_volume(None, max(0.0, min(2.0, self.volume + delta)))

    def apply_volume(self):
        """Applique le gain demandé au moteur média. Certains moteurs Android plafonnent à 100 %."""
        try:
            if self.sound:
                self.sound.volume = self.volume
            if self.video_widget:
                self.video_widget.volume = self.volume
        except Exception:
            pass
        percent = f"{int(round(self.volume * 100))}%"
        for attr in ("library_volume_label", "player_volume_label"):
            label = getattr(self, attr, None)
            if label is not None:
                label.text = percent

    def change_volume(self, _widget, value):
        self.volume = max(0.0, min(2.0, float(value)))
        self.apply_volume()
        # Synchronise le curseur de l'autre écran sans reconstruire l'interface.
        for attr in ("library_volume_slider", "player_volume_slider"):
            slider = getattr(self, attr, None)
            if slider is not None and abs(float(slider.value) - self.volume) > 0.005:
                slider.value = self.volume
        self.save_settings()

    def filter_media(self, _widget, value):
        q = value.strip().lower()
        self.filtered = [p for p in self.media if q in display_name(p).lower()]
        self.render_media()

    def render_media(self):
        if self.media_list is None:
            return
        self.media_list.clear_widgets()
        self.count_label.text = f"{len(self.filtered)} fichier(s) trouvé(s)"
        if not self.filtered:
            self.media_list.add_widget(self.label(
                "Aucun média trouvé.\nVérifie les autorisations de fichiers Android.",
                14, 72, MUTED))
            return
        for path in self.filtered:
            kind = "VIDÉO" if is_video(path) else "AUDIO"
            prefix = "▣ " if is_video(path) else "♫ "
            title = prefix + display_name(path) + "  ·  " + kind
            row_scroll = ScrollView(do_scroll_x=True, do_scroll_y=False,
                                    size_hint_y=None, height=dp(46), bar_width=dp(2),
                                    scroll_type=["content", "bars"])
            b = self.button(title, lambda _b, p=path: self.select_media(p),
                            44, (0.08, 0.11, 0.17, 0.94), self.font_size)
            b.size_hint = (None, None)
            b.width = max(dp(280), dp(18 + len(title) * max(7, self.font_size * 0.62)))
            b.height = dp(44)
            b.halign = "left"
            b.padding = [dp(10), 0]
            row_scroll.add_widget(b)
            self.media_list.add_widget(row_scroll)

    def refresh_library(self, *_):
        self.scan_media()
        self.render_media()

    def open_first(self, *_):
        if self.current_path and os.path.isfile(self.current_path):
            self.show_player()
            return
        target = next((p for p in self.filtered if not is_video(p)), None)
        if target is None and self.filtered:
            target = self.filtered[0]
        if target:
            self.select_media(target)
        else:
            self.message("Bibliothèque vide", "Aucun fichier trouvé. Vérifie les permissions Android.")

    def select_media(self, path):
        if self.playlist_panel is not None and self.playlist_panel.parent is self.root:
            self.root.remove_widget(self.playlist_panel)
        self.playlist_panel = None
        self.current_path = path
        self.audio_only = False
        if is_video(path):
            self.stop_audio()
        else:
            self.play_audio(path)
        self.show_player()

    # ---------- player ----------
    def stop_audio(self):
        try:
            if self.sound:
                self.sound.stop()
        except Exception:
            pass
        self.sound = None

    def play_audio(self, path):
        self.stop_audio()
        try:
            sound = SoundLoader.load(path)
            if sound is None:
                raise RuntimeError("Le lecteur Kivy ne prend pas en charge ce format sur cet appareil.")
            sound.volume = self.volume
            sound.loop = self.repeat
            sound.play()
            self.sound = sound
            self.current_path = path
            self.audio_only = False
        except Exception as exc:
            self.log_error(traceback.format_exc())
            self.message("Lecture impossible", f"Impossible de lire ce fichier.\n{exc}")

    def show_player(self, *_):
        """Lecteur vertical : titre, album, barre de progression et commandes. La photo de fond reste visible; aucune pochette supplémentaire ne s’affiche."""
        self.screen_name = "player"
        self.playlist_panel = None
        self.clear_root()
        self.page.padding = [dp(12), dp(7), dp(12), dp(8)]
        self.page.spacing = dp(5)

        # Ligne supérieure : retour à gauche, titre du lecteur et volume +/- à droite.
        top = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(5))
        top.add_widget(self.button("←", self.show_library, 38, PANEL, 20))
        top.add_widget(self.label("LECTEUR", 17, 38, WHITE, True))
        top.add_widget(self.label("VOL.", 10, 38, MUTED, True, fixed_font=True))
        top.add_widget(self.button("☷", self.toggle_playlist_panel, 38, PANEL, 17))
        self.page.add_widget(top)

        # Rectangle du titre du morceau.
        title_box = BoxLayout(size_hint_y=None, height=dp(38), padding=[dp(7), 0, dp(7), 0])
        with title_box.canvas.before:
            Color(0.035, 0.05, 0.08, 0.97)
            title_bg = Rectangle(pos=title_box.pos, size=title_box.size)
        title_box.bind(pos=lambda obj, val: setattr(title_bg, "pos", val),
                       size=lambda obj, val: setattr(title_bg, "size", val))
        self.now_label = Label(text=display_name(self.current_path) if self.current_path else "Aucun son",
                               color=WHITE, font_size=f"{max(12, min(28, self.font_size))}sp", bold=True, italic=True, halign="center", valign="middle")
        self.now_label.bind(size=lambda obj, val: setattr(obj, "text_size", val))
        title_box.add_widget(self.now_label)
        self.page.add_widget(title_box)

        # Petit rectangle de l'album placé juste sous le titre du son.
        album = self.get_album_title(self.current_path) if self.current_path else ""
        album_box = BoxLayout(size_hint_y=None, height=dp(26), padding=[dp(5), 0, dp(5), 0])
        with album_box.canvas.before:
            Color(0.08, 0.11, 0.17, 0.97)
            album_bg = Rectangle(pos=album_box.pos, size=album_box.size)
        album_box.bind(pos=lambda obj, val: setattr(album_bg, "pos", val),
                       size=lambda obj, val: setattr(album_bg, "size", val))
        album_box.add_widget(self.label(("Album : " + album) if album else "Album : non renseigné",
                                        11, 24, MUTED))
        self.page.add_widget(album_box)

        # Curseur horizontal à mouvement continu, avec amplification demandée jusqu'à 200 %.
        player_volume_row = BoxLayout(size_hint_y=None, height=dp(28), spacing=dp(6))
        player_volume_row.add_widget(self.label("VOLUME", 9, 26, MUTED, True, fixed_font=True))
        self.player_volume_slider = Slider(orientation="horizontal", min=0, max=2, value=self.volume,
                                           step=0.01, size_hint_x=1)
        self.player_volume_slider.bind(value=self.change_volume)
        player_volume_row.add_widget(self.player_volume_slider)
        self.player_volume_label = self.label(f"{int(round(self.volume * 100))}%", 10, 26, WHITE, True, fixed_font=True)
        player_volume_row.add_widget(self.player_volume_label)
        self.page.add_widget(player_volume_row)

        # Aucun visuel de pochette dans le lecteur audio : l’arrière-plan reste visible.
        # La seule image de contenu est BG.jpg. ic_launcher.png sert uniquement
        # de logo/icône de l’application, pas d’image superposée dans l’interface.
        if self.current_path and is_video(self.current_path) and not self.audio_only:
            try:
                self.video_widget = Video(source=self.current_path, state="play", volume=self.volume,
                                          allow_stretch=True, keep_ratio=True, size_hint=(1, 0.43))
                self.page.add_widget(self.video_widget)
            except Exception:
                self.page.add_widget(self.label("Vidéo non disponible", 14, 150, MUTED))
        else:
            # Espace flexible pour laisser apparaître le fond sans pochette ni logo en double.
            self.page.add_widget(BoxLayout(size_hint=(1, 1)))

        # Progression / indicateurs -10 s et +10 s.
        seek_row = BoxLayout(size_hint_y=None, height=dp(36), spacing=dp(5))
        seek_row.add_widget(self.button("−10 s", lambda *_: self.seek_current(-10), 34, PANEL, 10))
        self.progress_slider = Slider(min=0, max=100, value=0, size_hint_x=1)
        self.progress_slider.bind(on_touch_down=self._progress_touch_down,
                                  on_touch_up=self._progress_touch_up)
        seek_row.add_widget(self.progress_slider)
        seek_row.add_widget(self.button("+10 s", lambda *_: self.seek_current(10), 34, PANEL, 10))
        self.page.add_widget(seek_row)
        self.time_label = self.label("00:00 / 00:00", 10, 18, MUTED)
        self.page.add_widget(self.time_label)
        self._progress_event = Clock.schedule_interval(self.update_progress, 0.5)

        controls = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8), padding=[dp(12), 0, dp(12), 0])
        controls.add_widget(self.button("⏮", self.previous_track, 46, PANEL, 21))
        self.play_button = self.button("Ⅱ" if self.sound else "▶", self.toggle_play, 46, ACCENT, 20)
        controls.add_widget(self.play_button)
        controls.add_widget(self.button("⏭", self.next_track, 46, PANEL, 21))
        self.page.add_widget(controls)

        mode_row = BoxLayout(size_hint_y=None, height=dp(38), spacing=dp(5))
        mode_row.add_widget(self.button("Audio seul", self.toggle_audio_only, 36, PANEL, 11))
        mode_row.add_widget(self.button("Aléatoire : " + ("Oui" if self.shuffle else "Non"),
                                        self.toggle_shuffle, 36, PANEL, 10))
        mode_row.add_widget(self.button("Répéter : " + ("Oui" if self.repeat else "Non"),
                                        self.toggle_repeat, 36, PANEL, 10))
        self.page.add_widget(mode_row)

        # La petite liste de sons à droite est visible dès l'ouverture du lecteur.
        self.toggle_playlist_panel()

    def _progress_touch_down(self, slider, touch):
        if slider.collide_point(*touch.pos):
            self._slider_is_being_dragged = True
        return False

    def _progress_touch_up(self, slider, touch):
        if self._slider_is_being_dragged and slider.collide_point(*touch.pos):
            self._slider_is_being_dragged = False
            try:
                duration = self._current_duration()
                if duration > 0:
                    target = max(0.0, min(duration, float(slider.value)))
                    if self.sound and hasattr(self.sound, "seek"):
                        self.sound.seek(target)
                    elif self.video_widget and hasattr(self.video_widget, "seek"):
                        self.video_widget.seek(target / duration)
            except Exception:
                self.log_error(traceback.format_exc())
        else:
            self._slider_is_being_dragged = False
        return False

    def _current_duration(self):
        try:
            if self.video_widget and float(self.video_widget.duration or 0) > 0:
                return float(self.video_widget.duration)
            if self.sound and float(self.sound.length or 0) > 0:
                return float(self.sound.length)
        except Exception:
            pass
        return 0.0

    @staticmethod
    def _format_time(seconds):
        seconds = max(0, int(seconds or 0))
        return f"{seconds // 60:02d}:{seconds % 60:02d}"

    def update_progress(self, _dt):
        try:
            duration = self._current_duration()
            if self.video_widget and self.current_path and is_video(self.current_path):
                position = float(self.video_widget.position or 0)
            elif self.sound:
                position = float(self.sound.get_pos() or 0)
            else:
                position = 0.0
            if hasattr(self, "progress_slider") and self.progress_slider and not self._slider_is_being_dragged:
                self.progress_slider.max = max(duration, 1.0)
                self.progress_slider.value = min(position, self.progress_slider.max)
            if hasattr(self, "time_label") and self.time_label:
                self.time_label.text = f"{self._format_time(position)} / {self._format_time(duration)}"
            # Advance to the next track once an audio track finishes, when the backend
            # reports a usable duration and playback position.
            if (self.sound and not self.repeat and duration > 0 and
                    self.sound.state == "play" and position >= duration - 0.7 and
                    position > self._last_audio_position):
                self._last_audio_position = 0.0
                self.next_track()
            else:
                self._last_audio_position = position
        except Exception:
            pass

    def seek_current(self, seconds):
        """Avance ou recule si le moteur audio de l'appareil autorise seek()."""
        try:
            if self.sound and hasattr(self.sound, "seek"):
                pos = max(0, float(self.sound.get_pos()) + seconds)
                self.sound.seek(pos)
            elif self.video_widget and hasattr(self.video_widget, "seek"):
                pos = max(0, float(self.video_widget.position) + seconds)
                self.video_widget.seek(pos / max(float(self.video_widget.duration or 1), 1))
            else:
                self.message("Déplacement indisponible", "Le lecteur audio de cet appareil ne permet pas de déplacer la lecture pour ce fichier.")
        except Exception as exc:
            self.log_error(traceback.format_exc())
            self.message("Déplacement indisponible", str(exc))

    def get_album_title(self, path):
        """Renvoie le titre d'album si les métadonnées audio sont accessibles."""
        if not path or is_video(path):
            return ""
        try:
            from mutagen import File as MutagenFile
            audio = MutagenFile(path, easy=True)
            if audio and audio.get("album"):
                return str(audio["album"][0])
        except Exception:
            pass
        return ""

    def toggle_playlist_panel(self, *_):
        """Affiche/masque un petit panneau de sélection à droite du lecteur."""
        if self.playlist_panel is not None and self.playlist_panel.parent is self.root:
            self.root.remove_widget(self.playlist_panel)
            self.playlist_panel = None
            return
        # Dimensions demandées : largeur environ 5 cm, longueur/hauteur environ 6,3 cm.
        # Conversion approximative : 1 cm ≈ 37,8 dp ; la taille physique varie selon l'écran.
        panel = BoxLayout(orientation="vertical", spacing=dp(3), padding=dp(4),
                          size_hint=(None, None), size=(dp(189), dp(238)),
                          pos_hint={"right": 0.99, "top": 0.82})
        with panel.canvas.before:
            Color(0.035, 0.05, 0.08, 0.98)
            panel_bg = Rectangle(pos=panel.pos, size=panel.size)
        panel.bind(pos=lambda obj, val: setattr(panel_bg, "pos", val),
                   size=lambda obj, val: setattr(panel_bg, "size", val))
        panel.add_widget(self.label("SONS", 8, 13, WHITE, True, fixed_font=True))
        close_row = BoxLayout(size_hint_y=None, height=dp(13))
        close_row.add_widget(self.button("×", self.toggle_playlist_panel, 15, PANEL, 8, fixed_font=True))
        panel.add_widget(close_row)
        # La taille de police de cette mini-liste est fixe : les réglages A−/A+
        # ne la modifient pas. Les titres longs peuvent être parcourus horizontalement.
        scroll = ScrollView(do_scroll_x=False, bar_width=dp(2))
        items = GridLayout(cols=1, spacing=dp(2), size_hint_y=None)
        items.bind(minimum_height=items.setter("height"))
        track_count = 0
        for path in self.media:
            if is_video(path):
                continue
            name = display_name(path)
            track_row = ScrollView(
                do_scroll_x=True, do_scroll_y=False, size_hint_y=None,
                height=dp(15), bar_width=0, scroll_type=["content", "bars"]
            )
            # Largeur calculée d'après le titre : les noms longs restent accessibles
            # par glissement horizontal au lieu d'être coupés à droite.
            btn_width = max(dp(181), dp(8 + len(name) * 4.8))
            btn = self.button(name, lambda _b, p=path: self.select_media(p),
                              15, PANEL, 8, fixed_font=True)
            btn.size_hint = (None, None)
            btn.width = btn_width
            btn.height = dp(15)
            btn.halign = "left"
            btn.padding = [dp(4), 0]
            track_row.add_widget(btn)
            items.add_widget(track_row)
            track_count += 1
        if track_count == 0:
            items.add_widget(self.label("Aucun son", 8, 15, MUTED, fixed_font=True))
        scroll.add_widget(items)
        panel.add_widget(scroll)
        self.playlist_panel = panel
        self.root.add_widget(panel)

    def search_from_player(self, _widget, value):
        q = value.strip().lower()
        if len(q) < 2:
            return
        found = next((p for p in self.media if q in display_name(p).lower()), None)
        if found:
            self.select_media(found)

    def toggle_play(self, *_):
        if self.current_path is None:
            self.open_first()
            return
        if is_video(self.current_path) and self.video_widget and not self.audio_only:
            try:
                self.video_widget.state = "pause" if self.video_widget.state == "play" else "play"
                self.play_button.text = "▶ Lire" if self.video_widget.state == "pause" else "Ⅱ Pause"
            except Exception:
                pass
            return
        if is_video(self.current_path) and self.audio_only:
            self.message("Mode audio seul",
                         "La lecture audio d'une vidéo dépend du moteur vidéo Android. Si aucun son ne sort, ce format n'est pas pris en charge.")
            return
        if not self.sound:
            self.play_audio(self.current_path)
        else:
            try:
                if self.sound.state == "play":
                    self.sound.stop()
                    self.play_button.text = "▶ Lire"
                else:
                    self.sound.play()
                    self.play_button.text = "Ⅱ Pause"
            except Exception:
                self.play_audio(self.current_path)

    def previous_track(self, *_):
        self.move_track(-1)

    def next_track(self, *_):
        self.move_track(1)

    def move_track(self, direction):
        tracks = [p for p in self.media if not is_video(p)]
        if not tracks:
            self.message("Aucun audio", "Aucune musique audio n'a été trouvée.")
            return
        if self.shuffle and len(tracks) > 1:
            choices = [p for p in tracks if p != self.current_path]
            target = random.choice(choices or tracks)
        else:
            try:
                idx = tracks.index(self.current_path)
            except ValueError:
                idx = 0 if direction > 0 else len(tracks) - 1
            target = tracks[(idx + direction) % len(tracks)]
        self.current_path = target
        self.audio_only = False
        self.play_audio(target)
        self.show_player()

    def toggle_audio_only(self, *_):
        if not self.current_path or not is_video(self.current_path):
            self.message("Mode audio seul", "Sélectionne d'abord un fichier vidéo.")
            return
        self.audio_only = not self.audio_only
        if self.audio_only and self.video_widget:
            try:
                self.video_widget.state = "stop"
            except Exception:
                pass
        self.show_player()

    def toggle_shuffle(self, *_):
        self.shuffle = not self.shuffle
        self.save_settings()
        self.show_player()

    def toggle_repeat(self, *_):
        self.repeat = not self.repeat
        if self.sound:
            try:
                self.sound.loop = self.repeat
            except Exception:
                pass
        self.save_settings()
        self.show_player()

    # ---------- settings/menu ----------
    def open_menu(self, *_):
        box = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(6))
        pop = Popup(title="DESTIN SONOR — Réglages", content=box, size_hint=(0.92, 0.88))

        box.add_widget(self.label("Images fixes du projet : BG.jpg en arrière-plan et ic_launcher.png comme icône uniquement.", 11, 44, MUTED))
        box.add_widget(self.label("Taille du texte (hors mini-liste des sons)", 13, 22, MUTED))
        row = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(6))
        row.add_widget(self.button("A−", lambda *_: self.adjust_font(-1), 40, PANEL))
        row.add_widget(self.button("A+", lambda *_: self.adjust_font(1), 40, PANEL))
        box.add_widget(row)
        box.add_widget(self.label("Couleur du texte", 13, 22, MUTED))
        row2 = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(5))
        for name, color in [
            ("Blanc", list(WHITE)), ("Vert", [0.25, 1, 0.55, 1]),
            ("Bleu", [0.35, 0.65, 1, 1]), ("Rose", [1, 0.45, 0.7, 1])
        ]:
            row2.add_widget(self.button(name, lambda *_a, c=color: self.set_text_color(c), 40, PANEL, 11))
        box.add_widget(row2)
        box.add_widget(self.button("Ouvrir un fichier audio / vidéo", lambda *_: (pop.dismiss(), self.open_file_picker()), 44, PANEL, 13))
        box.add_widget(self.button("Configurer / changer le code PIN", lambda *_: (pop.dismiss(), self.configure_pin()), 44, PANEL, 13))
        if self.pin_enabled:
            box.add_widget(self.button("Verrouiller maintenant", lambda *_: (pop.dismiss(), self.lock_now()), 44, PANEL, 13))
            box.add_widget(self.button("Désactiver le code PIN", lambda *_: (pop.dismiss(), self.disable_pin()), 44, PANEL, 13))
        box.add_widget(self.button("À propos et limites", lambda *_: self.show_about(), 42, PANEL, 13))
        box.add_widget(self.button("Fermer", lambda *_: pop.dismiss(), 42))
        pop.open()

    def open_file_picker(self):
        """Ouvre le sélecteur intégré pour choisir un fichier audio ou vidéo."""
        start_path = "/storage/emulated/0"
        if not os.path.isdir(start_path):
            start_path = str(Path.home())
        chooser = FileChooserListView(
            path=start_path, filters=["*.mp3", "*.wav", "*.ogg", "*.flac", "*.m4a",
                                      "*.aac", "*.mp4", "*.mkv", "*.avi", "*.mov",
                                      "*.webm", "*.3gp", "*.m4v"],
            dirselect=False, multiselect=False
        )
        content = BoxLayout(orientation="vertical", spacing=dp(6), padding=dp(8))
        popup = Popup(title="Choisir un fichier", content=content, size_hint=(0.96, 0.9))
        content.add_widget(chooser)
        buttons = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(6))
        def open_selected(*_):
            if chooser.selection:
                selected = chooser.selection[0]
                if os.path.isfile(selected) and Path(selected).suffix.lower() in MEDIA_EXTS:
                    popup.dismiss()
                    if selected not in self.media:
                        self.media.append(selected)
                        self.media.sort(key=lambda item: display_name(item).lower())
                        self.filtered = list(self.media)
                    self.select_media(selected)
                else:
                    self.message("Fichier non valide", "Sélectionne un fichier audio ou vidéo pris en charge.")
        buttons.add_widget(self.button("Ouvrir", open_selected, 40, ACCENT, 12))
        buttons.add_widget(self.button("Annuler", lambda *_: popup.dismiss(), 40, PANEL, 12))
        content.add_widget(buttons)
        popup.open()

    def lock_now(self):
        if self.pin_enabled:
            self.is_unlocked = False
            self.show_pin_screen(initial=False)
        else:
            self.message("Verrouillage", "Configure d'abord un code PIN dans les réglages.")

    def adjust_font(self, delta):
        self.font_size = max(12, min(28, self.font_size + delta))
        self.save_settings()
        self.show_current_screen()

    def set_text_color(self, color):
        self.text_color = color
        self.save_settings()
        self.show_current_screen()

    def show_current_screen(self):
        if self.screen_name == "player":
            self.show_player()
        else:
            self.show_library()

    def show_about(self):
        self.message("À propos",
            "DESTIN SONOR — lecteur Kivy.\n\n"
            "Images : BG.jpg en arrière-plan et ic_launcher.png comme icône uniquement. "
            "La vidéo dépend des codecs du téléphone. La lecture fiable écran verrouillé, "
            "les notifications média et l'empreinte digitale nécessitent une intégration native.")

    # ---------- PIN lock ----------
    def show_pin_screen(self, initial=False):
        self.root.clear_widgets()
        self.page = BoxLayout(
            orientation="vertical", padding=dp(24), spacing=dp(12),
            size_hint=(1, 1), pos_hint={"x": 0, "y": 0}
        )
        self.root.add_widget(self.page)
        self.page.add_widget(self.label(APP_NAME, 25, 55, WHITE, True))
        self.page.add_widget(self.label(
            "Créer un code PIN" if initial else "Entrer le code PIN",
            17, 38, MUTED, True))
        pin1 = TextInput(password=True, multiline=False, hint_text="Code PIN (4 à 6 chiffres)",
                         size_hint_y=None, height=dp(48), input_filter="int",
                         font_size="18sp")
        self.page.add_widget(pin1)
        pin2 = None
        if initial:
            pin2 = TextInput(password=True, multiline=False, hint_text="Confirmer le code PIN",
                             size_hint_y=None, height=dp(48), input_filter="int",
                             font_size="18sp")
            self.page.add_widget(pin2)
        status = self.label("", 13, 38, MUTED)
        self.page.add_widget(status)

        def submit(*_):
            value = pin1.text.strip()
            if initial:
                if len(value) < 4 or len(value) > 6:
                    status.text = "Le code doit contenir 4 à 6 chiffres."
                    return
                if value != pin2.text.strip():
                    status.text = "Les deux codes ne correspondent pas."
                    return
                self.pin_hash = pin_digest(value)
                self.pin_enabled = True
                self.save_settings()
                self.is_unlocked = True
                self.show_library()
            else:
                if pin_digest(value) == self.pin_hash:
                    self.is_unlocked = True
                    self.show_library()
                else:
                    status.text = "Code incorrect. Réessaie."
                    pin1.text = ""

        self.page.add_widget(self.button("Valider", submit, 48))
        if not initial:
            self.page.add_widget(self.label(
                "Si tu oublies le code, ce prototype ne propose pas de récupération sécurisée.",
                12, 55, MUTED))

    def configure_pin(self):
        # If a PIN already exists, ask for the current one before changing.
        if self.pin_enabled:
            self.ask_current_pin(lambda: self.show_pin_screen(initial=True))
        else:
            self.show_pin_screen(initial=True)

    def ask_current_pin(self, on_success):
        box = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8))
        field = TextInput(password=True, multiline=False, hint_text="Code PIN actuel",
                          input_filter="int", size_hint_y=None, height=dp(44))
        info = self.label("", 12, 28, MUTED)
        pop = Popup(title="Vérification", content=box, size_hint=(0.86, 0.4))
        box.add_widget(field)
        box.add_widget(info)
        def verify(*_):
            if pin_digest(field.text.strip()) == self.pin_hash:
                pop.dismiss()
                on_success()
            else:
                info.text = "Code incorrect."
                field.text = ""
        box.add_widget(self.button("Continuer", verify, 42))
        pop.open()

    def disable_pin(self):
        self.ask_current_pin(self._disable_pin_confirmed)

    def _disable_pin_confirmed(self):
        self.pin_hash = ""
        self.pin_enabled = False
        self.save_settings()
        self.message("Code désactivé", "Le verrouillage par PIN est désactivé.")

    # ---------- lifecycle ----------
    def check_audio_end(self, _dt):
        # Kivy SoundLoader implementations do not all expose reliable end events.
        # This method intentionally avoids guessing duration or auto-advancing.
        return

    def on_pause(self):
        # Keep the Python activity resumable. This is best-effort only: a native
        # Android media foreground service is still needed for guaranteed playback.
        self.save_settings()
        return True

    def on_stop(self):
        self.save_settings()
        # Do not explicitly stop audio on activity stop: this avoids needlessly
        # cutting playback during some lifecycle transitions. Android may still
        # suspend/kill this process; see LISEZ_MOI.txt for the native-service limit.
        try:
            if self.video_widget:
                self.video_widget.state = "stop"
        except Exception:
            pass


if __name__ == "__main__":
    try:
        DestinSonorApp().run()
    except Exception:
        error_text = traceback.format_exc()
        try:
            with open("/storage/emulated/0/Download/destin_sonor_erreur.txt", "a", encoding="utf-8") as f:
                f.write("\n\n--- ERREUR AU DEMARRAGE ---\n" + error_text)
        except Exception:
            pass
        raise
