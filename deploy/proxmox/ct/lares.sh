#!/usr/bin/env bash
# Lares en un LXC de Proxmox, al estilo de los community-scripts.
#
#   bash -c "$(curl -fsSL https://raw.githubusercontent.com/ivancandelas/lares/main/deploy/proxmox/ct/lares.sh)"
#
# Se apoya en el motor de community-scripts (`build.func`), que es quien pinta
# el menú Default/Advanced, crea el contenedor y trae el modo actualización.
# Ellos lo dejaron preparado para repos de terceros: `COMMUNITY_SCRIPTS_URL`
# dice dónde están `ct/` e `install/`, y se resuelve aparte del motor.
#
# Lo que NO hace este archivo es instalar: de eso se encarga
# `deploy/native/install.sh`, el mismo que se usa fuera de Proxmox. Dos
# instaladores se separan en cuanto uno cambia, y entonces la mitad de los
# despliegues corre algo que nadie probó.

# Dónde viven nuestros ct/ e install/ (aquí, no en su repo).
COMMUNITY_SCRIPTS_URL="${COMMUNITY_SCRIPTS_URL:-https://raw.githubusercontent.com/ivancandelas/lares/main/deploy/proxmox}"
export COMMUNITY_SCRIPTS_URL

# El motor. Se puede fijar a un commit suyo si algún día cambian el contrato:
#   export COMMUNITY_SCRIPTS_CORE_URL=https://raw.githubusercontent.com/community-scripts/core/<commit>
source <(curl -fsSL "${COMMUNITY_SCRIPTS_CORE_URL:-https://raw.githubusercontent.com/community-scripts/core/main}/core/build.func")

APP="Lares"
var_tags="${var_tags:-home;erp;self-hosted}"
var_cpu="${var_cpu:-2}"
var_ram="${var_ram:-2048}"
var_disk="${var_disk:-20}"
var_os="${var_os:-debian}"
var_version="${var_version:-13}"
var_unprivileged="${var_unprivileged:-1}"

header_info "$APP"
variables
color
catch_errors

function update_script() {
  header_info
  check_container_storage
  check_container_resources

  if [[ ! -L /opt/lares/current ]]; then
    msg_error "Aquí no hay una instalación de ${APP}"
    exit
  fi

  # El actualizador de verdad vive con la aplicación: hace copia de la base
  # antes de migrar y sabe volver atrás moviendo un enlace.
  msg_info "Actualizando ${APP}"
  if /opt/lares/current/deploy/native/update.sh; then
    msg_ok "Actualizado"
  else
    msg_error "No salió bien. Para volver:  lares-update --rollback"
  fi
  exit
}

start
build_container
description

msg_ok "Completed successfully!\n"
echo -e "${CREATING}${GN}${APP} está instalado.${CL}"
echo -e "${INFO}${YW}Entra por:${CL}"
echo -e "${GATEWAY}${BGN}http://${IP}:8000${CL}"
echo -e "${INFO}${YW}Crea el primer usuario dentro del contenedor:${CL}"
echo -e "${TAB}${BGN}lares-manage createsuperuser${CL}"
