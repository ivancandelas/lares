#!/usr/bin/env bash
# Corre DENTRO del LXC recién creado por ct/lares.sh.
#
# Deliberadamente corto: prepara el contenedor con los helpers de
# community-scripts y luego llama al instalador nativo de Lares, que es el que
# se prueba. Reescribir aquí la instalación con sus helpers daría un script más
# "suyo" y dos instaladores que se separan a la primera versión.

source /dev/stdin <<<"$FUNCTIONS_FILE_PATH"
color
verb_ip6
catch_errors
setting_up_container
network_check
update_os

msg_info "Instalando lo que hace falta debajo"
$STD apt-get install -y curl ca-certificates openssl sudo git
msg_ok "Listo lo de debajo"

msg_info "Instalando Lares (paciencia: compila dependencias)"
LARES_VERSION="${LARES_VERSION:-}"
$STD bash -c "curl -fsSL https://raw.githubusercontent.com/ivancandelas/lares/main/deploy/native/install.sh \
    | bash -s -- $LARES_VERSION"
msg_ok "Lares instalado"

motd_ssh
customize

msg_info "Limpiando"
$STD apt-get -y autoremove
$STD apt-get -y autoclean
msg_ok "Limpio"
