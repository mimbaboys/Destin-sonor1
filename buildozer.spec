[app]
title = DESTIN SONOR
package.name = destinsonor
package.domain = org.destinsonor
source.dir = .
source.include_exts = py,jpg,png,txt,json
version = 1.0.0
requirements = python3,kivy,mutagen
orientation = portrait
fullscreen = 0
icon.filename = %(source.dir)s/ic_launcher.png
presplash.filename = %(source.dir)s/BG.jpg

# Permissions to discover local audio/video files on Android.
android.permissions = READ_MEDIA_AUDIO,READ_MEDIA_VIDEO,READ_EXTERNAL_STORAGE
android.api = 35
android.minapi = 23
android.ndk = 27c
android.archs = arm64-v8a, armeabi-v7a
android.accept_sdk_license = True

[buildozer]
log_level = 2
warn_on_root = 1
