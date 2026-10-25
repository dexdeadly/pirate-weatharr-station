"""
On-screen language for the PWS renderer.

The channel's visible text is localised here so a station can render in
English (the default) or neutral Spanish, chosen by the user in the plugin's
Language setting and passed to the renderer via ``--lang``.

English is the fallback everywhere: ``tr()`` returns the key unchanged unless
the active language is Spanish and a translation exists, so code that predates
the language feature keeps rendering exactly as before. Keys that contain
``{placeholder}`` tokens are formatted with the ``tr(key, **values)`` form.
"""
from __future__ import annotations

_LANG = "en"


def set_language(lang: str | None) -> None:
    """Pick the active language; anything unrecognised falls back to English."""
    global _LANG
    value = (lang or "en").strip().lower()
    _LANG = "es" if value in ("es", "español", "spanish") else "en"


def current() -> str:
    return _LANG


# English string -> neutral Spanish. The English string doubles as the lookup
# key, so English needs no table of its own and stays the safe default.
_ES = {
    # -- page titles -----------------------------------------------------
    "Current Conditions": "Condiciones actuales",
    "12-Hour Trend": "Tendencia de 12 horas",
    "7-Day Forecast": "Pronóstico de 7 días",
    "Live Radar": "Radar en vivo",
    "Regional Conditions": "Condiciones regionales",
    "Forecast Highs": "Máximas previstas",
    "Extended Forecast": "Pronóstico extendido",
    "Surf Report": "Reporte de surf",
    "Almanac": "Almanaque",

    # -- header / chrome -------------------------------------------------
    "NOW SHOWING": "EN PANTALLA",
    "CURRENTLY": "ACTUALMENTE",
    "LOCAL TIME": "HORA LOCAL",
    "Pirate Weather Station": "Estación Meteorológica Pirate Weather",

    # -- ticker ----------------------------------------------------------
    "ALERTS": "ALERTAS",
    "NEWS": "NOTICIAS",
    "WEATHER": "CLIMA",
    "STATUS": "ESTADO",
    "Weather data loading…": "Cargando datos del clima…",
    "Pirate Weather unavailable — {error}": "Pirate Weather no disponible — {error}",

    # -- alert bar -------------------------------------------------------
    "NO ALERTS": "SIN ALERTAS",
    "WARNING": "AVISO",
    "ALERT": "ALERTA",
    "NO DATA": "SIN DATOS",
    "UPDATED {stamp}": "ACTUALIZADO {stamp}",
    "DATA DELAYED · {stamp}": "DATOS CON RETRASO · {stamp}",
    "{i} OF {n}": "{i} DE {n}",
    "until {when}": "hasta {when}",
    "Alert status unavailable - weather data could not be refreshed":
        "Estado de alertas no disponible: no se pudieron actualizar los datos meteorológicos",
    "No active weather alerts": "No hay alertas meteorológicas activas",
    "No active weather alerts for this area": "No hay alertas meteorológicas activas para esta zona",

    # -- current conditions ----------------------------------------------
    "Feels like": "Sensación de",
    "Feels": "Sensación de",
    "Wind": "Viento",
    "Humidity": "Humedad",
    "Dew Point": "Punto de rocío",
    "Pressure": "Presión",
    "Visibility": "Visibilidad",
    "UV Index": "Índice UV",
    "Cloud Cover": "Nubosidad",
    "Chance of Precip": "Prob. de precipitación",
    "Precip Chance": "Prob. de precipitación",
    "Temperature": "Temperatura",
    "Wind Gusts": "Ráfagas",
    "accumulation": "acumulación",
    "High": "Máxima",
    "Low": "Mínima",
    "Sunrise": "Amanecer",
    "Sunset": "Atardecer",
    "Dawn": "Alba",
    "Dusk": "Anochecer",
    "Moon Phase": "Fase lunar",
    "Ozone": "Ozono",
    "Rain Today": "Lluvia de hoy",
    "Snow Today": "Nieve de hoy",
    "Ice Today": "Hielo de hoy",
    "Fire Index": "Índice de incendio",
    "Smoke": "Humo",
    "Elevation": "Elevación",
    "Nearest Storm": "Tormenta más cercana",
    "None nearby": "Ninguna cerca",
    "Calm": "En calma",

    # -- periods ---------------------------------------------------------
    "Today": "Hoy",
    "Tomorrow": "Mañana",
    "Tonight": "Esta noche",
    "Overnight": "Madrugada",
    "TODAY": "HOY",
    "DAY {n}": "DÍA {n}",

    # -- precipitation types ---------------------------------------------
    "precip": "precip.",
    "precipitation": "precipitación",
    "rain": "lluvia",
    "snow": "nieve",
    "sleet": "aguanieve",
    "hail": "granizo",
    "ice": "hielo",

    # -- moon phases -----------------------------------------------------
    "New Moon": "Luna nueva",
    "Waxing Crescent": "Luna creciente",
    "First Quarter": "Cuarto creciente",
    "Waxing Gibbous": "Gibosa creciente",
    "Full Moon": "Luna llena",
    "Waning Gibbous": "Gibosa menguante",
    "Last Quarter": "Cuarto menguante",
    "Waning Crescent": "Luna menguante",

    # -- surf report -----------------------------------------------------
    "FLAT": "PLANO",
    "POOR": "MALO",
    "FAIR": "REGULAR",
    "GOOD": "BUENO",
    "EPIC": "ÉPICO",
    "Primary": "Principal",
    "Secondary": "Secundaria",
    "Primary Swell": "Oleaje principal",
    "Secondary Swell": "Oleaje secundario",
    "Swell": "Oleaje",
    "Water Temp": "Temp. del agua",
    "ESTIMATED SURF": "OLEAJE ESTIMADO",
    "TIDES": "MAREAS",
    "5-DAY WAVE OUTLOOK": "PREVISIÓN DE OLAS A 5 DÍAS",
    "HIGH": "ALTA",
    "LOW": "BAJA",
    "No marine forecast for this spot - check the surf spot coordinates.":
        "No hay pronóstico marino para este punto: revisa las coordenadas del spot de surf.",
    "No NOAA tide station near this spot (tide predictions cover US coasts only).":
        "No hay estación de mareas NOAA cerca de este punto (las mareas solo cubren las costas de EE. UU.).",
    "Surf report loading...": "Cargando reporte de surf…",
    "Waves {h} @ {p} {d}": "Olas {h} @ {p} {d}",

    # -- radar -----------------------------------------------------------
    "Acquiring radar imagery…": "Obteniendo imágenes de radar…",
    "RADAR": "RADAR",
    "Light": "Ligero",
    "HEAVY": "FUERTE",

    # -- maps ------------------------------------------------------------
    "Map data unavailable": "Datos del mapa no disponibles",
    "Regional data unavailable": "Datos regionales no disponibles",
    "Forecast map data unavailable": "Datos del mapa de máximas no disponibles",

    # -- empty states ----------------------------------------------------
    "Forecast data unavailable": "Datos del pronóstico no disponibles",
    "No forecast available": "No hay pronóstico disponible",
    "Almanac data unavailable": "Datos del almanaque no disponibles",
    "Hourly data unavailable": "Datos horarios no disponibles",
    "Precip": "Precip.",
    "Gusts": "Ráfagas",
    "Cloud": "Nubes",

    # -- narrative sentences ---------------------------------------------
    "Highs near {h}°{u} with overnight lows around {l}°{u}.":
        "Máximas cercanas a {h}°{u} con mínimas nocturnas alrededor de {l}°{u}.",
    "Highs near {h}°{u}.": "Máximas cercanas a {h}°{u}.",
    "About a {p}% chance of {t}": "Alrededor de un {p}% de probabilidad de {t}",
    ", with up to {a} {u} possible": ", con hasta {a} {u} posibles",
    "Little to no precipitation expected.": "Se espera poca o ninguna precipitación.",
    "Winds {c} near {w} {u}": "Vientos del {c} cerca de {w} {u}",
    ", gusting to {g} {u}": ", con ráfagas de hasta {g} {u}",
    "Humidity around {h}%": "Humedad alrededor del {h}%",
    " with a dew point near {d}°{u}": " con punto de rocío cercano a {d}°{u}",
    "mostly clear skies": "cielos mayormente despejados",
    "partly cloudy skies": "cielos parcialmente nublados",
    "mostly cloudy skies": "cielos mayormente nublados",
    "overcast skies": "cielos cubiertos",
    "Expect {d} at about {p}% cloud cover.":
        "Se espera {d} con alrededor del {p}% de nubosidad.",
    "very high": "muy alto",
    "high": "alto",
    "UV index peaking at {u} ({d}); sun protection advised.":
        "Índice UV máximo de {u} ({d}); se recomienda protección solar.",

    # -- regional / WMO summaries ----------------------------------------
    "Clear": "Despejado",    "Mostly Clear": "Mayormente despejado",
    "Partly Cloudy": "Parcialmente nublado",
    "Overcast": "Cubierto",
    "Fog": "Niebla",
    "Freezing Fog": "Niebla helada",
    "Light Drizzle": "Llovizna ligera",
    "Drizzle": "Llovizna",
    "Heavy Drizzle": "Llovizna intensa",
    "Freezing Drizzle": "Llovizna helada",
    "Light Rain": "Lluvia ligera",
    "Rain": "Lluvia",
    "Heavy Rain": "Lluvia intensa",
    "Freezing Rain": "Lluvia helada",
    "Light Snow": "Nieve ligera",
    "Snow": "Nieve",
    "Heavy Snow": "Nieve intensa",
    "Snow Grains": "Cinarra",
    "Showers": "Chubascos",
    "Heavy Showers": "Chubascos intensos",
    "Snow Showers": "Chubascos de nieve",
    "Thunderstorms": "Tormentas",

    # -- condition labels (icon-key based; replaces the API's English summary
    #    when the channel is in Spanish). Keys are prefixed "cond:" so they
    #    don't collide with the precip-type keys ("rain"/"snow") above.
    "cond:clear-day": "Despejado",
    "cond:clear-night": "Despejado",
    "cond:partly-cloudy-day": "Parcialmente nublado",
    "cond:partly-cloudy-night": "Parcialmente nublado",
    "cond:cloudy": "Nublado",
    "cond:fog": "Niebla",
    "cond:rain": "Lluvia",
    "cond:snow": "Nieve",
    "cond:wind": "Ventoso",
    "cond:thunderstorm": "Tormenta eléctrica",

    # -- fallbacks / misc ------------------------------------------------
    "Current conditions": "Condiciones actuales",
    "Unknown": "Desconocido",
    " and more": " y más",
}


def tr(key: str, **fmt) -> str:
    """Translate ``key`` (which is also the English text)."""
    text = _ES.get(key, key) if _LANG == "es" else key
    if fmt:
        try:
            return text.format(**fmt)
        except (KeyError, IndexError, ValueError):
            return text
    return text
