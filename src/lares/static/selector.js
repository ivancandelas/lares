// Selector con búsqueda, para cuando las opciones no caben en un desplegable.
//
// Tres capas, y cada una existe porque la anterior se queda corta:
//
//   1. escribes y salen los que coinciden -lo normal-;
//   2. "y N más" te dice que hay otros, en vez de callarse: saber que no está
//      entre los diez primeros no es lo mismo que saber que no existe;
//   3. "+" crea el que falta, sin salir del formulario.
//
// Por debajo del umbral no se usa esto: un desplegable de cuatro opciones se
// maneja mejor con el control nativo, que funciona sin JavaScript y ya sabe
// abrirse con el teclado.
window.selector = function (clave, preset, nombre, inicialId, inicialTexto) {
  return {
    abierto: false,
    buscando: false,
    texto: inicialTexto || "",
    elegidoId: inicialId || "",
    elegidoTexto: inicialTexto || "",
    resultados: [],
    total: 0,
    hayMas: false,
    marcado: -1,
    temporizador: null,

    get vacio() {
      return !this.buscando && this.texto && this.resultados.length === 0;
    },

    alEscribir() {
      // Escribir invalida lo elegido: si no, se queda el nombre viejo en la
      // caja y el id nuevo debajo, y se guarda otra cosa distinta de la que
      // se lee en pantalla.
      this.elegidoId = "";
      this.abierto = true;
      clearTimeout(this.temporizador);
      this.temporizador = setTimeout(() => this.buscar(), 180);
    },

    async buscar() {
      this.buscando = true;
      const p = preset ? `&preset=${encodeURIComponent(preset)}` : "";
      const r = await fetch(
        `/opciones/${clave}/?q=${encodeURIComponent(this.texto)}${p}`,
        { headers: { "X-Requested-With": "XMLHttpRequest" } });
      this.buscando = false;
      if (!r.ok) { this.resultados = []; return; }
      const d = await r.json();
      this.resultados = d.results;
      this.total = d.total;
      this.hayMas = d.more;
      this.marcado = -1;
    },

    abrir() {
      this.abierto = true;
      if (this.resultados.length === 0) this.buscar();
    },

    elegir(op) {
      this.elegidoId = op.id;
      this.elegidoTexto = op.label;
      this.texto = op.label;
      this.abierto = false;
    },

    limpiar() {
      this.elegidoId = "";
      this.elegidoTexto = "";
      this.texto = "";
      this.resultados = [];
      this.abierto = false;
    },

    cerrar() {
      // Al salir sin elegir se restaura lo que había: dejar texto suelto que
      // no corresponde a nada hace creer que se guardó algo.
      this.texto = this.elegidoTexto;
      this.abierto = false;
      this.marcado = -1;
    },

    bajar() {
      if (!this.abierto) return this.abrir();
      this.marcado = Math.min(this.marcado + 1, this.resultados.length - 1);
    },

    subir() {
      this.marcado = Math.max(this.marcado - 1, 0);
    },

    aceptar() {
      if (this.marcado >= 0 && this.resultados[this.marcado]) {
        this.elegir(this.resultados[this.marcado]);
      }
    },

    // Lo que ve quien no elige nada: el campo oculto que se envía de verdad.
    get nombreCampo() {
      return nombre;
    },
  };
};
