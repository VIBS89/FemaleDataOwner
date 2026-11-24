"""Preguntas sobre el propio asistente y conversación de cortesía (F3, F12).

En un chat la gente también pregunta por la herramienta: cómo se entera de tablas nuevas, qué puede hacer, si ve los
datos de los clientes, quién puede ver qué. Buscar eso en el catálogo no devuelve nada, así que se responde aquí, con
hechos del funcionamiento real y, donde aplica, con lo que el usuario puede ver (sus bases de datos).

El tema se detecta por reglas; cuando hay un modelo configurado, el flujo también le pregunta el tema si la búsqueda no
encontró nada. El texto de cada respuesta es fijo: el modelo nunca redacta cómo funciona la herramienta.
"""

from __future__ import annotations

import re

from converdata.catalog.store import Catalog
from converdata.memory.text import strip_accents

TOPICS = (
    "greeting", "thanks", "farewell", "identity", "capabilities", "freshness", "sources", "privacy", "databases",
    "corrections", "permissions", "execution", "confidence",
)

_GREETING = r"(?:hola+|buenos dias|buen dia|buenas(?: tardes| noches)?|que tal|saludos|hey|hello|hi)"
_LEADING_GREETING = re.compile(rf"^\W*{_GREETING}\b[\s,.!¡:;-]*")
_QUESTION_WORD = re.compile(r"\b(donde|que|como|cual|cuales|cuant\w+|quien|por que|cuando)\b")

_RULES: list[tuple[str, re.Pattern]] = [
    ("farewell", re.compile(r"\b(adios|hasta (luego|pronto|manana)|nos vemos|chao|bye)\b")),
    ("identity", re.compile(
        r"\b(quien eres|que eres|como te llamas|que es converdata|para que (sirves|sirve (converdata|esto|este asistente|"
        r"esta herramienta))|eres (un|una) (robot|bot|ia|persona))\b")),
    ("execution", re.compile(
        r"\b(puedes|podrias|puede|sabes) (ejecutar|correr|lanzar|hacer|generar|escribir)\b.*\b(consultas?|quer(y|ies)|sql)\b"
        r"|\b(ejecutas|generas|corres) (consultas?|sql|quer(y|ies))\b"
        r"|\bconsultas? directo en la base\b|\bme (das|puedes dar|darias) (el resultado|las cifras|los numeros)\b")),
    ("freshness", re.compile(
        r"\b(como|cuando|cada cuanto|con que frecuencia|que tan)\b.*\b(te (actualizas|enteras|mantienes|sincronizas|refrescas)|"
        r"se (entera|actualiza|refresca|sincroniza) (converdata|el asistente|el catalogo|tu informacion)|"
        r"(actualiza|refresca) (tu informacion|el catalogo)|actualizad[oa] (estas|esta tu|esta el catalogo))\b"
        r"|\b(tablas?|columnas?|campos?|bases?(?: de datos)?) nuev[oa]s?\b.*\b(como|entera\w*|actualiz\w+|sabes|detecta\w*|"
        r"aparece\w*|ves)\b"
        r"|\b(como|entera\w*|sabes|detecta\w*)\b.*\b(nuev[oa]s? (tablas?|columnas?|campos?|bases?)|"
        r"(tablas?|columnas?|campos?|bases?(?: de datos)?) nuev[oa]s?)\b"
        r"|\bcada cuanto se actualiza (tu|la) informacion\b")),
    ("sources", re.compile(
        # En segunda persona o sobre sus respuestas: "¿de dónde sale el indicador de mora?" es una pregunta de datos.
        r"\bde donde (sacas|obtienes|tomas|traes)\b"
        r"|\bde donde (sale|viene|salen|vienen) (tu informacion|tus respuestas|lo que (me )?(respondes|dices)|"
        r"la informacion que (me )?(das|respondes))\b"
        r"|\b(en que te basas|cual es tu fuente|cuales son tus fuentes|como sabes (eso|lo que))\b")),
    # "¿Dónde puedes ver los datos de contacto de los clientes?" pregunta por un dato, no por el asistente.
    ("privacy", re.compile(
        r"^(?!.*\bdonde\b).*\b(ves|puedes ver|tienes acceso a|guardas|lees|almacenas)\b.*\b(datos|informacion|saldos|"
        r"nombres|registros|valores)\b.*\b(clientes?|personas?|reales)\b"
        r"|^(?!.*\bdonde\b).*\b(ves|guardas|lees) (los|mis) datos\b|\bes seguro (usarte|preguntarte)\b")),
    # "¿Qué sistemas operativos hay en los dispositivos?" pregunta por un dato: aquí solo en segunda persona.
    ("databases", re.compile(
        r"\b(que|cuales|cuantas) (bases(?: de datos)?|sistemas|fuentes(?: de datos)?) (conoces|tienes|ves|manejas|cubres)\b"
        r"|\b(que|cuales|cuantas) bases(?: de datos)? (hay|estan) (disponibles|conectad\w+)\b"
        r"|\ba que (bases|sistemas) tienes acceso\b")),
    # "¿Cómo se corrige un pago mal aplicado?" pregunta por el negocio: aquí solo sobre sus respuestas y descripciones.
    ("corrections", re.compile(
        r"\b(si )?te equivocas\b|\b(tu|la|esa|una) respuesta\b.*\b(mal|incorrecta|equivocada|erronea)\b"
        r"|\bdescripcion\b.*\b(mal|incorrecta|equivocada|erronea)\b"
        r"|\bcomo (te|la|lo) (corrijo|corrige|corregir)\b"
        r"|\bcomo (reporto|aviso) (un error|que te equivocaste|una respuesta)\b")),
    ("permissions", re.compile(
        r"\b(todos los usuarios|todos los que usan|cualquiera|cualquier usuario|todo el mundo)\b.*\b(ven|ve|pueden ver|"
        r"puede ver) (lo mismo|lo que|todo|mis|las respuestas)\b"
        r"|\bpermisos? (por|segun) (rol|usuario|perfil)\b|\bhay permisos\b"
        r"|\bquien (puede|mas puede) ver (lo que|mis|las respuestas)\b")),
    # "La confianza del dispositivo" o "el porcentaje de uso" son datos: aquí solo la confianza de la respuesta.
    ("confidence", re.compile(
        r"\bque (significa|es|quiere decir) (la|el|ese|esa) (confianza|porcentaje)(?! (de|del)\b)\b"
        r"|\bcomo (calculas|se calcula) la confianza\b")),
    ("capabilities", re.compile(
        r"\bque (puedes|sabes|podes) hacer\b|\bque no puedes\b|\ben que (me |nos )?(puedes|podes) ayudar\b"
        r"|\bcomo te (uso|utilizo)\b|\bcomo funcionas\b"
        r"|\bcomo funciona (converdata|esto|el asistente|la herramienta|el chat)\b|\bque (tipo|clase) de preguntas\b"
        r"|\bque te puedo preguntar\b|^\W*(ayuda|help)\W*$")),
]
# Un agradecimiento o un "ok, listo" solo lo es si no trae nada más: "ok, el email del cliente" es una pregunta.
_ACK_WORDS = frozenset("""
    muchas mil gracias te lo agradezco agradecido agradecida genial perfecto excelente ok okay vale listo entendido de
    acuerdo super me sirvio sirve bastante mucho muy amable todo claro bien bueno eso era es por ahora nada mas ya
    quedo gusto
""".split())


def _norm(text: str) -> str:
    return strip_accents(text).lower().strip()


def strip_greeting(question: str) -> str:
    """"Buenas tardes, ¿dónde está el DUI?" → "¿dónde está el DUI?". El saludo no es parte de lo que se busca."""
    rest = question.strip()
    while True:  # "hola, buenas tardes, …": puede haber más de un saludo
        match = _LEADING_GREETING.match(_norm(rest))
        if not match or not rest[match.end():].strip():
            break
        rest = rest[match.end():].strip()
    return rest or question


def topic_of(question: str) -> str | None:
    """Tema de una pregunta sobre el asistente, o None si es una pregunta de datos."""
    q = _norm(question)
    greeted = False
    while (match := _LEADING_GREETING.match(q)):
        greeted, q = True, q[match.end():].strip()
    if greeted and not re.search(r"[a-z0-9]", q):
        return "greeting"
    for topic, pattern in _RULES:
        if pattern.search(q):
            return topic
    words = re.findall(r"[a-z0-9]+", q)
    if words and all(w in _ACK_WORDS for w in words):
        return "thanks"
    return None


EXAMPLES = (
    "¿Dónde está el DUI del cliente?",
    "¿Qué datos tenemos de préstamos?",
    "¿Cómo relaciono los pagos con el préstamo?",
)


def _visible_databases(catalog: Catalog, vis) -> list[tuple[str, int]]:
    counts: dict[str, set[str]] = {}
    for obj in catalog.objects:
        if obj.id in vis and obj.kind in ("table", "view"):
            counts.setdefault(obj.database, set()).add(obj.asset_key)
    return sorted((db, len(keys)) for db, keys in counts.items())


def answer(topic: str, catalog: Catalog, vis, *, ask_flow: bool = False) -> str:
    """Texto de la respuesta. Solo usa hechos del funcionamiento y lo que `vis` permite ver al usuario (F14)."""
    examples = " · ".join(EXAMPLES)
    if topic == "greeting":
        return ("Hola. Soy ConverData, el asistente de la Gerencia de Datos. Pregúntame con tus palabras por la "
                f"información del banco que necesitas ubicar o entender. Por ejemplo: {examples}")
    if topic == "thanks":
        return "Con gusto. Si alguna respuesta fue la correcta, márcala con «Es este»: así queda confirmada para todos."
    if topic == "farewell":
        return "Hasta luego. Aquí estaré cuando necesites ubicar otro dato."
    if topic == "identity":
        return ("Soy ConverData, el asistente de datos de la Gerencia de Datos. Te ayudo a encontrar dónde está una "
                "información del banco, qué significa, con qué se relaciona y quién es su responsable, sin que tengas "
                "que conocer los sistemas por dentro.")
    if topic == "capabilities":
        figures = ("También puedo consultar cifras con tus permisos." if ask_flow else
                   "Todavía no calculo cifras ni ejecuto consultas: te indico qué información usar y cómo se cruza.")
        return ("Puedo ayudarte a: ubicar un dato (en qué sistema y dónde está), explicar qué significa, mostrarte las "
                "reglas de negocio que le aplican, decirte cómo se relaciona con otra información, de dónde viene y "
                f"quién es su responsable. {figures} No modifico información, no veo los datos de los clientes y solo "
                f"muestro lo que tu usuario tiene permiso de ver. Prueba con: {examples}")
    if topic == "freshness":
        return ("No memorizo las bases de datos: leo su estructura cada vez que se ejecuta el descubrimiento de "
                "esquemas. Esa lectura recorre los sistemas registrados y detecta las tablas y columnas nuevas, las que "
                "cambiaron y las que se eliminaron. La lanza un administrador desde Administración → Descubrir esquemas "
                "(ahí mismo se registra una base de datos nueva) o una tarea programada en el servidor, con la "
                "frecuencia que defina el banco. Lo nuevo aparece en mis respuestas después de esa lectura, con una "
                "descripción sugerida por IA marcada como «sin revisar» hasta que el responsable la confirma. Las "
                "descripciones y correcciones hechas por personas se conservan en cada actualización, y tus permisos "
                "se vuelven a comprobar cada pocos minutos.")
    if topic == "sources":
        return ("De cuatro fuentes: la estructura de las bases de datos del banco (tablas, columnas y relaciones), los "
                "diccionarios de datos y documentos cargados, las reglas de negocio y los procesos de carga, y lo que "
                "confirman los responsables y los usuarios con «Es este». Cada respuesta indica de dónde sale su "
                "descripción y si una persona la revisó.")
    if topic == "privacy":
        return ("No. Solo conozco la estructura de la información: qué datos existen, dónde están y qué significan. "
                "No leo nombres, saldos ni ningún otro dato de clientes de los sistemas, y por eso tampoco pueden "
                "aparecer en mis respuestas. Lo que escribes en el chat queda registrado solo en la auditoría interna "
                "del banco: evita poner datos personales en tus preguntas.")
    if topic == "databases":
        dbs = _visible_databases(catalog, vis)
        if not dbs:
            return ("Con tu usuario no tengo ninguna base de datos visible. Si necesitas acceso, pídelo al responsable "
                    "del dominio.")
        shown = "; ".join(f"{db} ({n} tablas y vistas)" for db, n in dbs)
        return (f"Con tu usuario puedo mostrarte {len(dbs)} base{'s' if len(dbs) != 1 else ''} de datos: {shown}. "
                "Otra persona puede ver más o menos, según sus permisos.")
    if topic == "corrections":
        return ("Puedes corregirme de tres formas. En cada respuesta, «Es este» confirma el dato correcto y «No es» lo "
                "descarta: con eso mejoro para la próxima pregunta parecida. Si ninguna opción sirve, «Preguntar al "
                "responsable» le envía la duda al responsable del dominio. Y las descripciones las corrige el "
                "responsable en la sección Curación: el cambio queda para todos, con su historial.")
    if topic == "permissions":
        return ("Cada persona ve solo lo que su usuario de base de datos tiene permiso de leer. Dos usuarios pueden "
                "recibir respuestas distintas a la misma pregunta, y lo que no puedes ver no se menciona. Los permisos "
                "se vuelven a comprobar cada pocos minutos.")
    if topic == "execution":
        if ask_flow:
            return "Sí: puedo consultar cifras con tus permisos, siempre en modo de solo lectura."
        return ("Todavía no. En esta fase no ejecuto consultas ni devuelvo cifras: te indico qué información usar y "
                "cómo se cruza para que la consulta la haga tu equipo de datos. La consulta directa está prevista "
                "para la siguiente fase.")
    if topic == "confidence":
        return ("La confianza indica qué tan seguro es que el dato mostrado sea el que buscas. Sube cuando la "
                "descripción fue revisada por una persona, cuando hay reglas de negocio o confirmaciones previas y "
                "cuando varias fuentes coinciden. Por debajo de 60 % conviene confirmarlo con el responsable.")
    raise ValueError(f"tema desconocido: {topic}")
