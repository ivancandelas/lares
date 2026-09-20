"""Formularios del nucleo.

Todos heredan de LaresForm, que se encarga del aspecto. Django no conoce
Tailwind y poner las clases a mano en cada plantilla es la via rapida a que
dos formularios dejen de parecerse.
"""

from __future__ import annotations

import datetime as dt

from django import forms
from django.db import transaction

from .models import (
    Account,
    Connector,
    Document,
    Entry,
    Link,
    Location,
    ObligationRule,
    Party,
    Posting,
)
from .models.resource import Resource

INPUT = ("w-full rounded-sm border border-rule bg-white px-3 py-2 "
         "placeholder:text-soft focus:border-calm focus:outline-none")


# Lo que se puede elegir sin teclearlo. La del hogar va primero; las que ya
# aparecen en sus datos se anaden solas, para que nada existente deje de poder
# seleccionarse solo porque no estaba en esta lista.
MONEDAS = ["MXN", "USD", "EUR", "CAD", "GBP", "JPY", "CHF", "BRL", "COP",
           "ARS", "CLP", "PEN"]


class AccountChoiceField(forms.ModelChoiceField):
    """Un desplegable de cuentas que dice cuánto hay en cada una.

    Elegir "de que cuenta sale" sin ver el saldo obliga a abrir otra pantalla
    y volver. Es el dato que se necesita justo en ese momento y el que mas
    caro sale no tener: de ahi salen los sobregiros.
    """

    def __init__(self, *args, balances=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.balances = balances or {}

    def label_from_instance(self, obj):
        if obj.pk not in self.balances:
            return str(obj)
        saldo = self.balances[obj.pk]
        return f"{obj}  ·  {saldo:,.2f} {obj.currency}".rstrip()


class GroupedForm:
    """Lo que `core/form.html` necesita para poder pintar un formulario.

    La plantilla recorre `form.groups`, asi que un formulario que no lo tenga
    se renderiza **vacio y sin error**: la pagina responde 200 y no hay ni un
    campo. Paso con los formularios de gasto, traspaso e ingreso, que no
    heredaban de `LaresForm` por no ser de modelo.

    Va aparte de `LaresForm` justamente por eso: agrupar y dar aspecto no tiene
    nada que ver con estar atado a un modelo.
    """

    GROUPS: tuple = ()

    @property
    def is_new(self) -> bool:
        """Si el objeto todavía no está en la base.

        **No sirve `instance.pk`.** Las claves son UUID con valor por defecto,
        asi que un objeto sin guardar YA tiene pk y cualquier `if instance.pk`
        se cumple siempre. De ahi salian dos fallos: el formulario de miembro
        reventaba al invitar, y la cadencia por defecto de una linea de
        proyecto no se aplicaba nunca.
        """
        instancia = getattr(self, "instance", None)
        return instancia is None or instancia._state.adding

    def _estilar(self):
        self._moneda_como_lista()
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs["class"] = "h-4 w-4 rounded-sm border-rule text-calm"
                continue
            if isinstance(field, forms.DateField):
                widget.input_type = "date"
            widget.attrs.setdefault("class", INPUT)
            if isinstance(widget, forms.Textarea):
                widget.attrs.setdefault("rows", 3)

    def _moneda_como_lista(self):
        """La moneda se elige, no se teclea.

        Escribirla a mano deja "mxn", "Mxn" y "MX" conviviendo en la base, y
        entonces cualquier suma por moneda deja de cuadrar.
        """
        campo = self.fields.get("currency")
        if campo is None or isinstance(campo.widget, forms.Select):
            return

        propia = getattr(getattr(self, "household", None), "currency", "")
        actual = self.initial.get("currency") or getattr(
            getattr(self, "instance", None), "currency", "")
        codigos = []
        for codigo in [propia, actual, *MONEDAS]:
            if codigo and codigo not in codigos:
                codigos.append(codigo)

        opciones = [(c, c) for c in codigos]
        if not campo.required:
            opciones.insert(0, ("", "—"))
        self.fields["currency"] = forms.ChoiceField(
            choices=opciones, required=campo.required, label=campo.label,
            help_text=campo.help_text,
            initial=actual or propia or codigos[0],
        )

    def _saldos_en(self, nombres, household):
        """Pone el saldo al lado de cada cuenta en los campos indicados."""
        from .models import Account

        if not household:
            return
        saldos = Account.balances(household)
        for nombre in nombres:
            campo = self.fields.get(nombre)
            if campo is None or not hasattr(campo, "queryset"):
                continue
            nuevo = AccountChoiceField(
                queryset=campo.queryset, required=campo.required,
                label=campo.label, help_text=campo.help_text,
                balances=saldos, empty_label=getattr(campo, "empty_label", None),
            )
            nuevo.widget.attrs.update(campo.widget.attrs)
            nuevo.initial = campo.initial
            self.fields[nombre] = nuevo

    def groups(self):
        """[(titulo, [campos])] para la plantilla. Sin GROUPS, un solo bloque."""
        if not self.GROUPS:
            return [("", list(self))]

        por_nombre = {campo.name: campo for campo in self}
        salida, usados = [], set()
        for titulo, nombres in self.GROUPS:
            campos = [por_nombre[n] for n in nombres if n in por_nombre]
            if campos:
                salida.append((titulo, campos))
                usados.update(c.name for c in campos)
        # Lo que no se listó no se pierde: va al final.
        sobrantes = [c for c in self if c.name not in usados]
        if sobrantes:
            salida.append(("Otros datos", sobrantes))
        return salida


class LaresForm(GroupedForm, forms.ModelForm):
    """Base con el aspecto ya resuelto y las fechas como selector nativo.

    `GROUPS` parte el formulario en bloques con titulo. Veinticinco campos
    seguidos son un muro: agrupados se rellenan sin leerlos todos, y el titulo
    dice cuando un bloque no aplica ("Solo si vives de renta").
    """

    def __init__(self, *args, household=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.household = household
        self._estilar()
        if household:
            self._scope_choices(household)

    def _scope_choices(self, household):
        """Los desplegables solo muestran cosas del hogar activo."""
        for field in self.fields.values():
            queryset = getattr(field, "queryset", None)
            if queryset is not None and any(
                f.name == "household" for f in queryset.model._meta.fields
            ):
                field.queryset = queryset.model._base_manager.filter(household=household)

    def save(self, commit=True):
        obj = super().save(commit=False)
        if self.household and hasattr(obj, "household_id") and not obj.household_id:
            obj.household = self.household
        if commit:
            obj.save()
            self.save_m2m()
        return obj


class ResourceForm(LaresForm):
    """Base de los formularios de recurso que aportan los modulos."""

    COMMON = ["name", "owner", "location", "status", "acquired_on",
              "purchase_amount", "current_value", "currency", "description"]

    def save(self, commit=True):
        obj = super().save(commit=False)
        if not obj.kind:
            obj.kind = getattr(obj, "resource_kind", "")
        if commit:
            obj.save()
            self.save_m2m()
        return obj


class PartyForm(LaresForm):
    """Las etiquetas se escriben separadas por comas.

    Es el gesto que todo el mundo conoce y no obliga a mantener una lista de
    categorías antes de poder guardar a alguien.
    """

    GROUPS = (
        ("Quién es", ["kind", "name", "legal_name", "birth_date"]),
        ("Cómo lo agrupas", ["tags"]),
        ("Datos fiscales", ["tax_id"]),
        ("Notas", ["notes"]),
    )

    tags = forms.CharField(
        required=False, label="Etiquetas",
        help_text="Separadas por comas: familia, trabajo, amigos.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_new:
            from .models.tagging import tags_of

            self.fields["tags"].initial = ", ".join(
                t.name for t in tags_of(self.instance)
            )

    def save(self, commit=True):
        party = super().save(commit=commit)
        if commit:
            from .models.tagging import set_tags

            set_tags(party, (self.cleaned_data.get("tags") or "").split(","))
        return party

    class Meta:
        model = Party
        fields = ["kind", "name", "legal_name", "tax_id", "birth_date", "notes"]
        labels = {
            "kind": "Persona u organización",
            "name": "Cómo lo llamas",
            "legal_name": "Nombre legal",
            "tax_id": "RFC",
            "birth_date": "Fecha de nacimiento",
            "notes": "Notas",
        }
        help_texts = {
            "tax_id": "Sirve para reconocer sus facturas automáticamente.",
        }


class LocationForm(LaresForm):
    class Meta:
        model = Location
        fields = ["name", "parent", "code"]
        labels = {"name": "Nombre", "parent": "Está dentro de", "code": "Etiqueta QR o NFC"}


class DocumentForm(LaresForm):
    """Un documento suelto no sirve: lo que importa es a qué pertenece."""

    GROUPS = (
        ("Qué es", ["title", "doc_type", "file", "attach_to"]),
        ("Fechas", ["issued_on", "expires_on"]),
        ("Importe y emisor", ["issuer", "amount", "currency"]),
        ("Privacidad", ["confidentiality"]),
    )

    attach_to = forms.ModelChoiceField(
        queryset=Resource.objects.none(), required=False,
        label="Pertenece a", help_text="El coche, la casa o la tarjeta a la que se refiere.",
    )

    class Meta:
        model = Document
        fields = ["title", "doc_type", "file", "issuer", "issued_on", "expires_on",
                  "amount", "currency", "confidentiality"]
        labels = {
            "title": "Qué es",
            "doc_type": "Tipo",
            "file": "Archivo",
            "issuer": "Quién lo emitió",
            "issued_on": "Fecha de emisión",
            "expires_on": "Vence el",
            "amount": "Importe",
            "currency": "Moneda",
            "confidentiality": "Privacidad",
        }
        help_texts = {
            "expires_on": "Si lo rellenas, el aviso de renovación se crea solo.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.household:
            self.fields["attach_to"].queryset = Resource._base_manager.filter(
                household=self.household, archived_at__isnull=True
            )

    @transaction.atomic
    def save(self, commit=True):
        doc = super().save(commit=commit)
        destino = self.cleaned_data.get("attach_to")
        if destino and commit:
            from django.contrib.contenttypes.models import ContentType
            Link.objects.get_or_create(
                household=self.household,
                source_type=ContentType.objects.get_for_model(Document),
                source_id=doc.pk,
                role="documents",
                target_type=ContentType.objects.get_for_model(destino.__class__),
                target_id=destino.pk,
                valid_from=None,
            )
        return doc


class ObligationRuleForm(LaresForm):
    """Reglas propias sin pedirle JSON a nadie."""

    GROUPS = (
        ("Qué", ["label", "amount", "currency", "counterparty"]),
        ("Cada cuánto", ["periodicity", "day", "month", "on_date"]),
    )

    PERIODICIDAD = [
        ("monthly", "Cada mes"),
        ("yearly", "Cada año"),
        ("every2", "Cada dos meses"),
        ("once", "Una sola vez"),
    ]

    periodicity = forms.ChoiceField(choices=PERIODICIDAD, label="Cada cuánto")
    day = forms.IntegerField(min_value=1, max_value=31, label="Día del mes", initial=1)
    month = forms.IntegerField(min_value=1, max_value=12, required=False,
                               label="Mes", help_text="Solo para las anuales.")
    on_date = forms.DateField(required=False, label="Fecha",
                              help_text="Solo para las de una sola vez.")

    class Meta:
        model = ObligationRule
        fields = ["label", "amount", "currency", "counterparty"]
        labels = {
            "label": "Qué hay que pagar o hacer",
            "amount": "Importe",
            "currency": "Moneda",
            "counterparty": "A quién",
        }

    def clean(self):
        data = super().clean()
        periodicidad = data.get("periodicity")
        if periodicidad == "yearly" and not data.get("month"):
            self.add_error("month", "Una regla anual necesita saber en qué mes.")
        if periodicidad == "once" and not data.get("on_date"):
            self.add_error("on_date", "Indica la fecha.")
        return data

    def save(self, commit=True):
        rule = super().save(commit=False)
        data = self.cleaned_data
        periodicidad = data["periodicity"]
        if periodicidad == "monthly":
            rule.schedule = {"monthly": {"day": data["day"]}}
        elif periodicidad == "yearly":
            rule.schedule = {"yearly": {"month": data["month"], "day": data["day"]}}
        elif periodicidad == "every2":
            inicio = dt.date.today().replace(day=min(data["day"], 28))
            rule.schedule = {"every": {"months": 2}, "from": inicio.isoformat()}
        else:
            rule.schedule = {"on_date": data["on_date"].isoformat()}

        if not rule.key:
            rule.key = rule.label.lower().replace(" ", "_")[:80]
        rule.remind_offsets = rule.remind_offsets or [-7, -3, -1]
        if commit:
            rule.save()
        return rule


class AccountForm(LaresForm):
    class Meta:
        model = Account
        fields = ["name", "type", "institution", "last_four", "currency"]
        labels = {
            "name": "Nombre",
            "type": "Qué es",
            "institution": "Banco o entidad",
            "last_four": "Últimos 4 dígitos",
            "currency": "Moneda",
        }
        help_texts = {
            "last_four": "Nunca guardes el número completo.",
            "type": "El efectivo es una cuenta como cualquier otra: márcalo "
                    "como activo. Así sacar del cajero es un traspaso entre "
                    "dos cuentas tuyas, no un gasto.",
        }


class ExpenseForm(GroupedForm, forms.Form):
    """Registrar un gasto sin que nadie tenga que saber qué es un asiento.

    Por dentro escribe partida doble; por fuera pregunta tres cosas. Si el
    usuario tiene que entender contabilidad, la interfaz falló.
    """

    GROUPS = (
        ("Qué y cuánto", ["date", "description", "amount"]),
        ("De dónde sale", ["paid_from", "category"]),
        ("A quién y sobre qué", ["merchant", "about", "for_whom"]),
    )

    date = forms.DateField(label="Cuándo", initial=dt.date.today)
    description = forms.CharField(max_length=300, label="En qué")
    amount = forms.DecimalField(max_digits=16, decimal_places=2, min_value=0,
                                label="Cuánto")
    paid_from = forms.ModelChoiceField(queryset=Account.objects.none(),
                                       label="Pagado con")
    category = forms.ModelChoiceField(queryset=Account.objects.none(), label="Categoría")
    merchant = forms.ModelChoiceField(
        queryset=Party.objects.none(), required=False, label="En dónde o a quién",
        help_text="Walmart, la escuela, el taller. Luego podrás ver cuánto llevas ahí.",
    )
    about = forms.ModelChoiceField(
        queryset=Resource.objects.none(), required=False, label="Sobre qué",
        help_text="Asócialo a un coche o a la casa y sabrás cuánto te cuesta de verdad.",
    )
    for_whom = forms.ModelChoiceField(
        queryset=Party.objects.none(), required=False, label="Para quién",
        help_text="La mesada del hijo, lo de tu pareja. Es distinto del comercio.",
    )

    def __init__(self, *args, household=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.household = household
        self._estilar()

        if household:
            cuentas = Account._base_manager.filter(household=household, is_active=True)
            self.fields["paid_from"].queryset = cuentas.filter(
                type__in=[Account.Type.ASSET, Account.Type.LIABILITY]
            )
            self.fields["category"].queryset = cuentas.filter(type=Account.Type.EXPENSE)
            self._saldos_en(["paid_from"], household)
            self.fields["about"].queryset = Resource._base_manager.filter(
                household=household, archived_at__isnull=True
            )
            partes = Party._base_manager.filter(household=household,
                                                archived_at__isnull=True)
            self.fields["merchant"].queryset = partes
            self.fields["for_whom"].queryset = partes

    @transaction.atomic
    def save(self) -> Entry:
        data = self.cleaned_data
        entry = Entry.objects.create(
            household=self.household, date=data["date"],
            description=data["description"], source="manual",
            counterparty=data.get("merchant"),
        )
        importe = data["amount"]
        # Dos apuntes que suman cero: el gasto carga, la cuenta abona.
        Posting.objects.create(
            household=self.household, entry=entry, account=data["category"],
            amount=importe, dimension=data.get("about"),
            beneficiary=data.get("for_whom"),
        )
        Posting.objects.create(
            household=self.household, entry=entry, account=data["paid_from"],
            amount=-importe,
        )
        return entry


# ---------------------------------------------------------------------------
# Conectores
# ---------------------------------------------------------------------------


class ConnectorForm(LaresForm):
    """Base de los formularios de conector.

    El secreto se pide siempre en blanco: si ya hay uno guardado, dejarlo vacío
    lo conserva. Así no se enseña nunca en pantalla ni viaja de vuelta al
    navegador.
    """

    secret = forms.CharField(
        required=False, widget=forms.PasswordInput(render_value=False),
        label="Contraseña o token",
    )

    class Meta:
        model = Connector
        fields = ["label", "is_active"]
        labels = {"label": "Cómo lo llamas", "is_active": "Activo"}

    CONFIG_FIELDS: tuple = ()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        instance = kwargs.get("instance") or self.instance
        if instance and instance.has_secret:
            self.fields["secret"].help_text = "Ya hay uno guardado. Déjalo vacío para conservarlo."
        for name in self.CONFIG_FIELDS:
            if name in self.fields and instance and instance.pk:
                self.fields[name].initial = instance.config.get(name)

    def save(self, commit=True):
        connector = super().save(commit=False)
        connector.key = self.CONNECTOR_KEY
        connector.config = {
            **(connector.config or {}),
            **{name: self.cleaned_data.get(name) for name in self.CONFIG_FIELDS},
        }
        if nuevo := self.cleaned_data.get("secret"):
            connector.secret = nuevo
        if commit:
            connector.save()
        return connector


class PaperlessConnectorForm(ConnectorForm):
    CONNECTOR_KEY = "paperless"
    CONFIG_FIELDS = ("base_url", "tag", "page_size", "write_back")

    base_url = forms.URLField(
        label="Dirección de Paperless", assume_scheme="https",
        help_text="Por ejemplo https://paperless.casa.local",
    )
    tag = forms.CharField(required=False, label="Solo esta etiqueta",
                          help_text="Vacío: trae todo lo reciente.")
    page_size = forms.IntegerField(min_value=1, max_value=200, initial=25,
                                   label="Cuántos revisar cada vez",
                                   help_text="Es la red de seguridad del "
                                             "webhook, no la vía principal.")
    write_back = forms.BooleanField(
        required=False, label="Escribir el enlace de vuelta en Paperless",
        help_text="Rellena el campo personalizado «lares_url» de cada "
                  "documento. Hay que crearlo antes en Paperless.",
    )


class ImapConnectorForm(ConnectorForm):
    CONNECTOR_KEY = "imap"
    CONFIG_FIELDS = ("host", "port", "username", "folder", "allowed_senders")

    host = forms.CharField(label="Servidor IMAP")
    port = forms.IntegerField(initial=993, label="Puerto")
    username = forms.CharField(label="Usuario")
    folder = forms.CharField(initial="INBOX", label="Carpeta")
    allowed_senders = forms.CharField(
        label="Solo de estos remitentes",
        help_text="Separados por comas. Sin lista no se acepta nada: "
                  "un buzón abierto es un agujero.",
    )


class WatchFolderConnectorForm(ConnectorForm):
    CONNECTOR_KEY = "watchfolder"
    CONFIG_FIELDS = ("path", "delete_after")

    path = forms.CharField(label="Carpeta del servidor",
                           help_text="Donde el escáner deja lo que digitaliza.")
    delete_after = forms.BooleanField(required=False, label="Borrar el original tras recogerlo")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields.pop("secret", None)       # una carpeta no tiene contraseña


class DisposalForm(LaresForm):
    """Dar de baja algo sin borrarlo.

    Un activo no desaparece cuando sale de tu vida: cambia de estado y conserva
    su historia. Y si se vendió, el importe permite que el patrimonio se corrija
    solo en vez de arrastrar algo que ya no tienes.
    """

    class Meta:
        model = Resource
        fields = ["disposal_reason", "disposed_on", "disposed_to",
                  "disposal_amount", "disposal_note"]
        labels = {
            "disposal_reason": "Qué pasó",
            "disposed_on": "Cuándo",
            "disposed_to": "A quién",
            "disposal_amount": "Importe",
            "disposal_note": "Nota",
        }
        help_texts = {
            "disposed_to": "Solo si lo vendiste, lo regalaste o lo traspasaste.",
            "disposal_amount": "Lo que te pagaron, si aplica.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["disposal_reason"].required = True
        self.fields["disposed_on"].required = True
        self.fields["disposed_on"].initial = dt.date.today()

    def save(self, commit=True):
        recurso = super().save(commit=False)
        recurso.status = Resource.Status.DISPOSED
        if commit:
            recurso.save()
        return recurso


class TransferForm(GroupedForm, forms.Form):
    """Mover dinero entre dos cuentas tuyas.

    Sacar del cajero, pasar de la nomina al ahorro, pagar la tarjeta: en los
    tres casos el dinero no se gasta, cambia de sitio. Registrarlo como gasto
    es el error mas comun de cualquier sistema de finanzas personales, y el
    mas caro: el dinero se cuenta dos veces -una al moverlo y otra al
    gastarlo de verdad- y todo lo demas queda mal.

    Por dentro son dos apuntes que suman cero contra dos cuentas de activo o
    pasivo, sin tocar ninguna categoria de gasto. Por eso un traspaso no
    aparece en "en que se va el dinero", que es exactamente lo correcto.
    """

    GROUPS = (
        ("Cuánto y cuándo", ["date", "amount"]),
        ("Entre qué cuentas", ["origin", "destination"]),
        ("Concepto", ["description"]),
    )

    date = forms.DateField(label="Cuándo", initial=dt.date.today)
    amount = forms.DecimalField(max_digits=16, decimal_places=2, min_value=0,
                                label="Cuánto")
    origin = forms.ModelChoiceField(queryset=Account.objects.none(),
                                    label="De qué cuenta sale")
    destination = forms.ModelChoiceField(queryset=Account.objects.none(),
                                         label="A qué cuenta entra")
    description = forms.CharField(max_length=300, required=False,
                                  label="Concepto",
                                  help_text="Opcional: «retiro del cajero», "
                                            "«pago de la tarjeta».")

    def __init__(self, *args, household=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.household = household
        self._estilar()
        if household:
            cuentas = Account._base_manager.filter(
                household=household, is_active=True,
                type__in=[Account.Type.ASSET, Account.Type.LIABILITY])
            self.fields["origin"].queryset = cuentas
            self.fields["destination"].queryset = cuentas
            self._saldos_en(["origin", "destination"], household)

    def clean(self):
        datos = super().clean()
        if datos.get("origin") and datos.get("origin") == datos.get("destination"):
            self.add_error("destination", "Tiene que ser otra cuenta.")
        return datos

    @transaction.atomic
    def save(self) -> Entry:
        datos = self.cleaned_data
        origen, destino = datos["origin"], datos["destination"]
        entry = Entry.objects.create(
            household=self.household, date=datos["date"], source="transfer",
            description=datos.get("description")
            or f"Traspaso de {origen.name} a {destino.name}",
        )
        importe = datos["amount"]
        # Un pasivo vive en negativo: abonar a la tarjeta SUBE su saldo
        # contable hacia cero, y por eso el signo es el mismo en los dos
        # casos. La cuenta de origen baja, la de destino sube.
        Posting.objects.create(household=self.household, entry=entry,
                               account=origen, amount=-importe)
        Posting.objects.create(household=self.household, entry=entry,
                               account=destino, amount=importe)
        return entry


class IncomeEntryForm(GroupedForm, forms.Form):
    """Registrar dinero que entró.

    El gasto tenia formulario y el ingreso no, asi que la unica forma de
    meter un sueldo era el importador de estados de cuenta o la consola.
    """

    GROUPS = (
        ("Qué y cuánto", ["date", "description", "amount"]),
        ("Dónde entró", ["into", "category", "payer"]),
    )

    date = forms.DateField(label="Cuándo", initial=dt.date.today)
    description = forms.CharField(max_length=300, label="De qué")
    amount = forms.DecimalField(max_digits=16, decimal_places=2, min_value=0,
                                label="Cuánto")
    into = forms.ModelChoiceField(queryset=Account.objects.none(),
                                  label="A qué cuenta entró")
    category = forms.ModelChoiceField(queryset=Account.objects.none(),
                                      label="Categoría")
    payer = forms.ModelChoiceField(queryset=Party.objects.none(), required=False,
                                   label="Quién te pagó")

    def __init__(self, *args, household=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.household = household
        self._estilar()
        if household:
            cuentas = Account._base_manager.filter(household=household,
                                                   is_active=True)
            self.fields["into"].queryset = cuentas.filter(
                type=Account.Type.ASSET)
            self.fields["category"].queryset = cuentas.filter(
                type=Account.Type.INCOME)
            self.fields["payer"].queryset = Party._base_manager.filter(
                household=household, archived_at__isnull=True)
            self._saldos_en(["into"], household)

    @transaction.atomic
    def save(self) -> Entry:
        datos = self.cleaned_data
        entry = Entry.objects.create(
            household=self.household, date=datos["date"], source="manual",
            description=datos["description"], counterparty=datos.get("payer"),
        )
        importe = datos["amount"]
        # Los ingresos viven en negativo en partida doble: la cuenta sube y
        # la categoria de ingreso baja la misma cantidad.
        Posting.objects.create(household=self.household, entry=entry,
                               account=datos["into"], amount=importe)
        Posting.objects.create(household=self.household, entry=entry,
                               account=datos["category"], amount=-importe)
        return entry


class HouseholdForm(LaresForm):
    """Los datos del hogar: cómo se llama y dónde vive.

    El nombre no es decorativo: sale en los correos de aviso, en la cabecera
    del paquete de sucesion y en el nombre del archivo de exportacion. Tenerlo
    solo en `bootstrap_household` obligaba a entrar al admin de Django o a la
    consola para corregir una errata.

    El pais y el estado tampoco lo son: deciden **que packs de obligaciones
    aplican** -refrendo, verificacion, predial-, asi que cambiarlos cambia el
    calendario. Por eso va dicho en el formulario y no en la documentacion.
    """

    GROUPS = (
        ("Cómo se llama", ["name"]),
        ("Dónde está", ["country", "subdivision", "timezone"]),
        ("Dinero", ["currency"]),
    )

    class Meta:
        from .models import Household

        model = Household
        fields = ["name", "country", "subdivision", "timezone", "currency"]
        labels = {
            "name": "Nombre del hogar",
            "country": "País",
            "subdivision": "Estado",
            "timezone": "Zona horaria",
            "currency": "Moneda",
        }
        help_texts = {
            "name": "Sale en los avisos por correo y en lo que compartes.",
            "country": "Código de dos letras: MX, ES, US.",
            "subdivision": "Decide qué obligaciones locales aplican: MX-JAL, "
                           "MX-CMX. Cambiarlo cambia el calendario.",
            "timezone": "Con qué reloj se cuentan los vencimientos.",
            "currency": "La de casa. Las demás se siguen pudiendo usar donde "
                        "haga falta.",
        }

    def clean_country(self):
        return (self.cleaned_data.get("country") or "").upper()

    def clean_currency(self):
        return (self.cleaned_data.get("currency") or "").upper()


class MemberForm(LaresForm):
    """Invitar a alguien o cambiar lo que puede ver.

    El correo va aparte del usuario porque casi siempre la persona todavia no
    existe: se crea al invitarla y entra por un enlace de un solo uso, sin que
    haga falta un servidor de correo. Eso importa en self-hosted, que es donde
    esto vive.
    """

    email = forms.EmailField(label="Correo", help_text=(
        "Con él entra. Si ya usa Lares, se le añade este hogar."))
    display_name = forms.CharField(max_length=120, required=False,
                                   label="Cómo se llama")

    GROUPS = (
        ("Quién", ["email", "display_name"]),
        ("Qué puede hacer", ["role", "expires_on"]),
        ("Sobre qué", ["scopes"]),
    )

    class Meta:
        from .models import Membership

        model = Membership
        fields = ["role", "expires_on", "scopes"]
        labels = {"role": "Rol", "expires_on": "El acceso caduca el",
                  "scopes": "Ámbitos"}
        help_texts = {
            "role": "«Solo lectura» y «profesional externo» pueden mirar pero "
                    "no registrar nada.",
            "expires_on": "Obligatorio para un profesional externo: un contador "
                          "no debería seguir entrando en octubre.",
            "scopes": "Vacío significa todo lo que su rol permita.",
        }

    def __init__(self, *args, **kwargs):
        from .permissions import scopes_available
        from .registry import registry

        super().__init__(*args, **kwargs)
        self.fields["scopes"] = forms.MultipleChoiceField(
            choices=scopes_available(registry), required=False,
            label="Ámbitos", widget=forms.CheckboxSelectMultiple,
            help_text="Vacío significa todo lo que su rol permita.",
            initial=list(self.instance.scopes or []) if not self.is_new else [],
        )
        if not self.is_new:
            self.fields["email"].initial = self.instance.user.email
            self.fields["email"].disabled = True
            self.fields["display_name"].initial = \
                self.instance.user.display_name

    def clean(self):
        from .models import Membership

        datos = super().clean()
        if (datos.get("role") == Membership.Role.PROFESSIONAL
                and not datos.get("expires_on")):
            self.add_error("expires_on",
                           "Un acceso profesional lleva fecha de caducidad.")
        return datos

    def save(self, commit=True):
        from .models import User

        membresia = super().save(commit=False)
        membresia.scopes = self.cleaned_data.get("scopes") or []
        membresia.household = self.household

        if self.is_new:
            correo = self.cleaned_data["email"].lower()
            usuario = User.objects.filter(email__iexact=correo).first()
            if usuario is None:
                usuario = User.objects.create_user(
                    username=correo, email=correo,
                    display_name=self.cleaned_data.get("display_name") or "",
                )
                # Sin contraseña utilizable: entra por el enlace y la pone.
                usuario.set_unusable_password()
                usuario.save(update_fields=["password"])
            membresia.user = usuario
        elif nombre := self.cleaned_data.get("display_name"):
            membresia.user.display_name = nombre
            membresia.user.save(update_fields=["display_name"])

        if commit:
            membresia.save()
        return membresia


class AcceptInviteForm(GroupedForm, forms.Form):
    """Poner una contraseña al entrar por primera vez."""

    password1 = forms.CharField(label="Contraseña", widget=forms.PasswordInput,
                                min_length=8)
    password2 = forms.CharField(label="Repítela", widget=forms.PasswordInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", INPUT)

    def clean(self):
        datos = super().clean()
        if datos.get("password1") != datos.get("password2"):
            self.add_error("password2", "No coinciden.")
        return datos


class EmergencyContactForm(LaresForm):
    """A quién se le libera qué, y después de cuánto silencio.

    Los dos plazos van juntos a proposito: sin ventana de gracia el silencio
    libera de golpe, y un viaje largo acabaria con los datos de alguien en el
    correo de su cunado sin que hubiera pasado nada.
    """

    GROUPS = (
        ("Quién", ["party", "name", "email", "relationship"]),
        ("Qué recibe", ["sections", "note"]),
        ("Cuándo", ["quiet_days", "grace_days"]),
    )

    class Meta:
        from .models import EmergencyContact

        model = EmergencyContact
        fields = ["party", "name", "email", "relationship", "sections", "note",
                  "quiet_days", "grace_days"]
        labels = {
            "party": "Si ya está en tus contactos",
            "name": "Cómo se llama",
            "email": "A qué correo se le avisa",
            "relationship": "Qué es tuyo",
            "note": "Qué quieres que sepa",
            "quiet_days": "Si no entras en",
            "grace_days": "Avisarte y esperar",
        }
        help_texts = {
            "party": "Así se usan sus teléfonos y correos, y no hay dos fichas "
                     "de la misma persona.",
            "email": "Solo si no está en contactos o quieres otro distinto.",
            "relationship": "Hermana, albacea, abogado. Sale en el paquete.",
            "note": "Lo primero que leerá. «La caja fuerte está en el clóset "
                    "de arriba; la combinación la tiene mi hermana.»",
            "quiet_days": "Días sin que entre nadie que administre el hogar.",
            "grace_days": "Días entre el aviso y la entrega. Entrar lo cancela.",
        }

    def __init__(self, *args, **kwargs):
        from .models import Party
        from .services.succession import SECCIONES, secciones_de

        super().__init__(*args, **kwargs)
        self.fields["party"].queryset = Party.objects.all()
        self.fields["party"].required = False
        self.fields["party"].empty_label = "No está, lo escribo aquí"
        self.fields["sections"] = forms.MultipleChoiceField(
            choices=SECCIONES, required=False, label="Qué recibe",
            widget=forms.CheckboxSelectMultiple,
            help_text="Lo que un tercero necesita, no todo el sistema.",
            initial=(secciones_de(self.instance) if not self.is_new
                     else [c for c, _ in SECCIONES]),
        )

    def clean(self):
        datos = super().clean()
        party = datos.get("party")
        if not party and not (datos.get("name") or "").strip():
            self.add_error("name", "Dinos a quién, aunque no esté en contactos.")

        # Sin correo no hay a dónde mandar el paquete el día que se libere, y
        # eso no se descubre solo: se descubre el día que ya no hay a quién
        # preguntarle.
        correo = (datos.get("email") or "").strip()
        if not correo and party:
            from .models import ContactPoint

            correo = (party.contact_points
                      .filter(channel=ContactPoint.Channel.EMAIL)
                      .exists())
        if not correo:
            self.add_error("email", "Hace falta un correo: es por donde le "
                                    "llegará el enlace.")
        return datos

    def save(self, commit=True):
        contacto = super().save(commit=False)
        contacto.sections = self.cleaned_data.get("sections") or []
        if contacto.party_id and not contacto.name:
            contacto.name = contacto.party.name
        if commit:
            contacto.save()
        return contacto
