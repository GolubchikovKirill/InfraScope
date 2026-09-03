Инсталляторы RustDesk для раздачи эндпоинтам.

Сюда кладётся файл из RUSTDESK_INSTALLER_FILENAME, например
rustdesk-1.4.9-x86_64.msi (github.com/rustdesk/rustdesk/releases).
Каталог монтируется в backend как /var/lib/infrascope/rustdesk (ro) и
раздаётся через GET /remote-access/deploy/installer.

На проде удобнее вынести каталог наружу репозитория:
RUSTDESK_PACKAGE_HOST_DIR=/var/lib/infrascope/rustdesk

Сами .msi/.exe в git не коммитятся.
