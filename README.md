# Enriquecedor

Backend FastAPI para la segunda Action del GPT. Su trabajo es **enriquecer** registros bibliográficos ya encontrados por tu primera Action usando:

- **Crossref** para DOI, licencias, funding, publisher, ORCID y señales de corrección/retractación.
- **OpenAlex** para `cited_by_count`, tipo de work, source/journal, open access y ROR.

## Estructura esperada

```text
Enriquecedor/
├── app/
│   ├── __init__.py
│   └── main.py
├── openapi.yaml
├── requirements.txt
├── Dockerfile
├── run_local.sh
├── run_local.bat
├── .env.example
└── README.md
```

## Requisitos

- Python 3.10 o superior
- Conexión a internet
- Cuenta en GitHub
- Cuenta en Render

## Variables de entorno

Crea un archivo `.env` a partir de `.env.example`.

```env
HTTP_USER_AGENT=Enriquecedor/1.0 (tu-correo@dominio.com)
CROSSREF_MAILTO=tu-correo@dominio.com
OPENALEX_API_KEY=
HTTP_TIMEOUT=25
MAX_LOOKUP_CANDIDATES=5
```

`OPENALEX_API_KEY` es opcional en el código, pero conviene dejar el soporte preparado porque OpenAlex anunció cambios de uso y precios en febrero de 2026. citeturn708000search1turn708000search13turn708000search19

## Instalación local

### Windows

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8001
```

### Mac / Linux

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8001
```

## Pruebas locales

### Health

Abre:

```text
http://127.0.0.1:8001/health
```

### Swagger

Abre:

```text
http://127.0.0.1:8001/docs
```

### Ejemplo de llamada a `/enrich`

```json
{
  "records": [
    {
      "record_id": "bio_rec_1",
      "title": "Chikungunya fever and associated systemic manifestations",
      "authors": ["Silva AB", "Ramos CD"],
      "year": 2021,
      "journal": "Travel Medicine and Infectious Disease",
      "pmid": "12345678",
      "pmcid": "PMC1234567",
      "doi": null,
      "links": {
        "pubmed_url": "https://pubmed.ncbi.nlm.nih.gov/12345678/"
      }
    }
  ],
  "fill_missing_doi": true,
  "fill_license": true,
  "fill_funding": true,
  "fill_publisher": true,
  "fill_orcid_ror": true,
  "fill_citation_metrics": true,
  "fill_open_access_flags": true,
  "check_updates_or_retractions": true
}
```

## Despliegue en Render

Render documenta para FastAPI este patrón base:

- **Build Command:** `pip install -r requirements.txt`
- **Start Command:** `uvicorn main:app --host 0.0.0.0 --port $PORT`

Como aquí tu aplicación vive en `app/main.py`, en este proyecto debes usar:

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Ese patrón coincide con la guía oficial de Render para FastAPI. citeturn708000search2turn708000search20

### Pasos

1. Sube esta carpeta a un repo de GitHub.
2. En Render crea un **Web Service**.
3. Conecta el repo.
4. Usa estos valores:

**Build Command**

```bash
pip install -r requirements.txt
```

**Start Command**

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

5. Espera el deploy.
6. Copia la URL pública de Render.
7. Reemplaza en `openapi.yaml`:

```yaml
servers:
  - url: https://TU-DOMINIO.onrender.com
```

por tu URL real.
8. Guarda el cambio y vuelve a subirlo a GitHub.
9. Importa `openapi.yaml` en tu GPT como segunda Action.

## Prueba mínima de éxito

Si esto funciona, ya está listo:

- `https://TU-URL.onrender.com/health`
- `https://TU-URL.onrender.com/docs`
- `POST /enrich` devuelve DOI, publisher, license, cited_by_count u otros campos enriquecidos cuando existan.

## Notas metodológicas

- Esta Action **no descubre literatura desde cero**. Solo enriquece registros ya identificados.
- Crossref usa `https://api.crossref.org/` como base de su REST API. citeturn708000search0turn708000search6
- OpenAlex usa `https://api.openalex.org` como base de su API. citeturn708000search1turn708000search4
- No todos los registros tendrán funding, ORCID o licencia disponible.
- Si una fuente falla, el backend devuelve notas de error parciales por registro.
