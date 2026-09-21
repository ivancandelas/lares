// Alta rápida: crear lo que falta sin perder el formulario de atrás.
//
// Se define como función global y no con Alpine.data() a propósito. Alpine se
// carga con `defer` en el <head>; un script del final del cuerpo se ejecuta
// ANTES que él, así que registrar un componente de Alpine desde aquí llegaría
// tarde. Una función global, en cambio, solo tiene que existir cuando Alpine
// evalúa el x-data, y eso ocurre después.
window.altaRapida = function (clave, preset, idSelect) {
  return {
    abierto: false,
    cargando: false,
    html: "",

    get url() {
      const p = preset ? `?preset=${encodeURIComponent(preset)}` : "";
      return `/rapido/${clave}/${p}`;
    },

    get token() {
      const campo = this.$el.closest("form").querySelector(
        "[name=csrfmiddlewaretoken]");
      return campo ? campo.value : "";
    },

    async abrir() {
      this.abierto = true;
      this.cargando = true;
      this.html = "";
      const r = await fetch(this.url, {
        headers: { "X-Requested-With": "XMLHttpRequest" },
      });
      this.html = await r.text();
      this.cargando = false;
      this.$nextTick(() => {
        const primero = this.$refs.cuerpo.querySelector(
          "input:not([disabled]), select:not([disabled])");
        if (primero) primero.focus();
      });
    },

    cerrar() {
      this.abierto = false;
      this.html = "";
    },

    async guardar() {
      // Se envía lo que hay dentro de la ventana, NO el formulario de atrás.
      // Ese es el punto de todo esto.
      const datos = new FormData();
      this.$refs.cuerpo.querySelectorAll("input, select, textarea").forEach(
        (c) => {
          if (!c.name) return;
          if ((c.type === "checkbox" || c.type === "radio") && !c.checked) return;
          datos.append(c.name, c.value);
        });

      this.cargando = true;
      const r = await fetch(this.url, {
        method: "POST",
        headers: { "X-CSRFToken": this.token, "X-Requested-With": "XMLHttpRequest" },
        body: datos,
      });
      this.cargando = false;

      if (r.status === 422) {          // se equivocó en algo: se repinta
        this.html = await r.text();
        return;
      }
      if (!r.ok) {
        this.html = '<p class="text-sm text-overdue">No se pudo crear.</p>';
        return;
      }

      const creado = await r.json();
      const select = document.getElementById(idSelect);
      const opcion = new Option(creado.label, creado.id, true, true);
      select.add(opcion);
      // Que reaccione lo que dependa de este campo (Alpine, validaciones).
      select.dispatchEvent(new Event("change", { bubbles: true }));
      this.cerrar();
    },
  };
};
