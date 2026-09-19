Инсталляторы RustDesk для раздачи эндпоинтам.

Сюда кладётся файл из RUSTDESK_INSTALLER_FILENAME, например
rustdesk-1.4.9-x86_64.msi (github.com/rustdesk/rustdesk/releases).
Каталог монтируется в backend как /var/lib/infrascope/rustdesk (ro) и
раздаётся через GET /remote-access/deploy/installer.

На проде удобнее вынести каталог наружу репозитория:
RUSTDESK_PACKAGE_HOST_DIR=/var/lib/infrascope/rustdesk

Сами .msi/.exe в git не коммитятся.

Для push-раскатки (rustdesk-ksc/Push-RustDesk.ps1) сюда же кладутся оба файла:
rustdesk-1.4.9-x86_64.msi (Windows 10/11 x64) и
rustdesk-1.4.9-x86-sciter.exe (Windows 7 и 32-бит; релиз rustdesk 1.4.9,
артефакт "x86-sciter"). Имена задаются в rustdesk-ksc.json
(installer_msi / installer_exe32).

