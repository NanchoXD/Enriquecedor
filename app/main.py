from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import httpx
from fastapi import FastAPI
from pydantic import BaseModel, Field

APP_TITLE = "Enriquecedor"
APP_VERSION = "1.0.0"

CROSSREF_BASE = os.getenv("CROSSREF_BASE", "https://api.crossref.org")
OPENALEX_BASE = os.getenv("OPENALEX_BASE", "https://api.openalex.org")
HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "25"))
HTTP_USER_AGENT = os.getenv(
    "HTTP_USER_AGENT",
    "Enriquecedor/1.0 (set-your-email@example.com)",
)
CROSSREF_MAILTO = os.getenv("CROSSREF_MAILTO", "")
OPENALEX_API_KEY = os.getenv("OPENALEX_API_KEY", "")
MAX_LOOKUP_CANDIDATES = int(os.getenv("MAX_LOOKUP_CANDIDATES", "5"))

app = FastAPI(title=APP_TITLE, version=APP_VERSION)


class InputRecord(BaseModel):
    record_id: str
    title: Optional[str] = None
    authors: List[str] = Field(default_factory=list)
    year: Optional[int] = None
    publication_date: Optional[str] = None
    journal: Optional[str] = None
    document_type: Optional[str] = None
    study_type: Optional[str] = None
    language: Optional[str] = None
    abstract: Optional[str] = None
    pmid: Optional[str] = None
    pmcid: Optional[str] = None
    doi: Optional[str] = None
    keywords: List[str] = Field(default_factory=list)
    mesh_terms: List[str] = Field(default_factory=list)
    access_status: Optional[str] = None
    links: Dict[str, Optional[str]] = Field(default_factory=dict)


class EnrichRequest(BaseModel):
    records: List[InputRecord]
    fill_missing_doi: bool = True
    fill_license: bool = True
    fill_funding: bool = True
    fill_publisher: bool = True
    fill_orcid_ror: bool = True
    fill_citation_metrics: bool = True
    fill_open_access_flags: bool = True
    check_updates_or_retractions: bool = True


class EnrichedRecord(BaseModel):
    record_id: str
    title: Optional[str] = None
    authors: List[str] = Field(default_factory=list)
    year: Optional[int] = None
    publication_date: Optional[str] = None
    journal: Optional[str] = None
    document_type: Optional[str] = None
    study_type: Optional[str] = None
    language: Optional[str] = None
    abstract: Optional[str] = None
    pmid: Optional[str] = None
    pmcid: Optional[str] = None
    doi: Optional[str] = None
    publisher: Optional[str] = None
    license: Optional[str] = None
    funding: List[str] = Field(default_factory=list)
    orcid: List[str] = Field(default_factory=list)
    ror: List[str] = Field(default_factory=list)
    cited_by_count: Optional[int] = None
    work_type: Optional[str] = None
    source_journal: Optional[str] = None
    is_open_access: Optional[bool] = None
    has_fulltext: Optional[bool] = None
    is_retracted_or_corrected: Optional[bool] = None
    access_status: Optional[str] = None
    links: Dict[str, Optional[str]] = Field(default_factory=dict)
    notes: List[str] = Field(default_factory=list)


class EnrichResponse(BaseModel):
    enrichment_id: str
    enriched_at: str
    source_counts: Dict[str, int]
    notes: List[str]
    records: List[EnrichedRecord]


def _safe_strip(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


DOI_PREFIX_RE = re.compile(r"^(https?://(dx\\.)?doi\\.org/)", re.I)


def normalize_doi(doi: Optional[str]) -> Optional[str]:
    doi = _safe_strip(doi)
    if not doi:
        return None
    doi = DOI_PREFIX_RE.sub("", doi)
    return doi.strip().rstrip(".")


def normalize_title(title: Optional[str]) -> str:
    if not title:
        return ""
    title = title.lower().strip()
    title = re.sub(r"<[^>]+>", " ", title)
    title = re.sub(r"[^a-z0-9\\s]", " ", title)
    title = re.sub(r"\\s+", " ", title)
    return title.strip()


def _year_from_date(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    match = re.search(r"(19|20)\\d{2}", text)
    return int(match.group(0)) if match else None


def _normalize_author_name(name: str) -> str:
    return re.sub(r"\\s+", " ", (name or "").strip())


def _first_author_lastname(record: InputRecord) -> Optional[str]:
    if not record.authors:
        return None
    author = _normalize_author_name(record.authors[0])
    if not author:
        return None
    return author.split()[0]


def build_http_headers() -> Dict[str, str]:
    return {
        "User-Agent": HTTP_USER_AGENT,
        "Accept": "application/json",
    }


async def get_json(client: httpx.AsyncClient, url: str, params: Optional[Dict[str, Any]] = None) -> Any:
    response = await client.get(url, params=params, headers=build_http_headers())
    response.raise_for_status()
    return response.json()


# ---------- Crossref ----------

def crossref_params_with_mailto(params: Dict[str, Any]) -> Dict[str, Any]:
    clean = {k: v for k, v in params.items() if v is not None and v != ""}
    if CROSSREF_MAILTO:
        clean["mailto"] = CROSSREF_MAILTO
    return clean


async def crossref_lookup_by_doi(client: httpx.AsyncClient, doi: str) -> Optional[dict]:
    doi = normalize_doi(doi)
    if not doi:
        return None
    url = f"{CROSSREF_BASE}/works/{quote(doi, safe='')}"
    data = await get_json(client, url, params=crossref_params_with_mailto({}))
    return data.get("message")


async def crossref_search_by_metadata(client: httpx.AsyncClient, record: InputRecord) -> Optional[dict]:
    params: Dict[str, Any] = {
        "rows": MAX_LOOKUP_CANDIDATES,
        "query.title": record.title or None,
        "query.author": _first_author_lastname(record),
        "query.container-title": record.journal or None,
        "select": "DOI,title,container-title,published-print,published-online,publisher,author,link,license,assertion,funder,relation,type,update-to",
    }
    url = f"{CROSSREF_BASE}/works"
    data = await get_json(client, url, params=crossref_params_with_mailto(params))
    items = data.get("message", {}).get("items", [])
    return choose_best_crossref_match(record, items)


def choose_best_crossref_match(record: InputRecord, items: List[dict]) -> Optional[dict]:
    if not items:
        return None
    target_title = normalize_title(record.title)
    target_year = record.year
    best_item: Optional[dict] = None
    best_score = -1

    for item in items:
        score = 0
        item_title = " ".join(item.get("title", [])[:1])
        norm_item_title = normalize_title(item_title)
        if target_title and norm_item_title == target_title:
            score += 6
        elif target_title and target_title and (target_title in norm_item_title or norm_item_title in target_title):
            score += 4

        item_year = extract_crossref_year(item)
        if target_year and item_year and target_year == item_year:
            score += 3

        container = " ".join(item.get("container-title", [])[:1]).strip().lower()
        if record.journal and container and record.journal.lower().strip() == container:
            score += 2

        if score > best_score:
            best_score = score
            best_item = item

    return best_item if best_score >= 4 else None


def extract_crossref_year(item: dict) -> Optional[int]:
    for key in ["published-print", "published-online", "published"]:
        date_parts = item.get(key, {}).get("date-parts", [])
        if date_parts and date_parts[0]:
            try:
                return int(date_parts[0][0])
            except Exception:
                continue
    return None


def parse_crossref_links(item: dict) -> Dict[str, Optional[str]]:
    links: Dict[str, Optional[str]] = {}
    doi = normalize_doi(item.get("DOI"))
    if doi:
        links["doi_url"] = f"https://doi.org/{doi}"

    raw_links = item.get("link") or []
    pdf_url = None
    publisher_url = None
    for entry in raw_links:
        content_type = (entry.get("content-type") or "").lower()
        intent = (entry.get("intended-application") or "").lower()
        candidate = entry.get("URL")
        if candidate and not publisher_url:
            publisher_url = candidate
        if candidate and ("pdf" in content_type or intent == "text-mining") and not pdf_url:
            pdf_url = candidate

    if pdf_url:
        links["pdf_url"] = pdf_url
    if publisher_url:
        links["publisher_url"] = publisher_url
    return links


def parse_crossref_license(item: dict) -> Optional[str]:
    licenses = item.get("license") or []
    if not licenses:
        return None
    url = licenses[0].get("URL") or licenses[0].get("url")
    return _safe_strip(url)


def parse_crossref_funding(item: dict) -> List[str]:
    funders = []
    for funder in item.get("funder") or []:
        name = _safe_strip(funder.get("name"))
        award = funder.get("award") or []
        if name and award:
            funders.append(f"{name} ({', '.join(str(x) for x in award if x)})")
        elif name:
            funders.append(name)
    return sorted(set(funders))


def parse_crossref_orcids(item: dict) -> List[str]:
    orcids = []
    for author in item.get("author") or []:
        value = _safe_strip(author.get("ORCID") or author.get("orcid"))
        if value:
            orcids.append(value)
    return sorted(set(orcids))


def parse_crossref_retraction_flag(item: dict) -> bool:
    if item.get("update-to"):
        return True
    relation = item.get("relation") or {}
    relation_text = str(relation).lower()
    flags = ["retract", "correct", "update", "withdraw"]
    return any(flag in relation_text for flag in flags)


# ---------- OpenAlex ----------

def openalex_params(params: Dict[str, Any]) -> Dict[str, Any]:
    clean = {k: v for k, v in params.items() if v is not None and v != ""}
    if OPENALEX_API_KEY:
        clean["api_key"] = OPENALEX_API_KEY
    return clean


async def openalex_lookup_by_doi(client: httpx.AsyncClient, doi: str) -> Optional[dict]:
    doi = normalize_doi(doi)
    if not doi:
        return None
    url = f"{OPENALEX_BASE}/works"
    params = openalex_params({"filter": f"doi:https://doi.org/{doi}", "per-page": 1})
    data = await get_json(client, url, params=params)
    results = data.get("results", [])
    return results[0] if results else None


async def openalex_search_by_metadata(client: httpx.AsyncClient, record: InputRecord) -> Optional[dict]:
    params = openalex_params({"search": record.title, "per-page": MAX_LOOKUP_CANDIDATES})
    if record.year:
        params["filter"] = f"publication_year:{record.year}"
    url = f"{OPENALEX_BASE}/works"
    data = await get_json(client, url, params=params)
    items = data.get("results", [])
    return choose_best_openalex_match(record, items)


def choose_best_openalex_match(record: InputRecord, items: List[dict]) -> Optional[dict]:
    if not items:
        return None
    target_title = normalize_title(record.title)
    target_year = record.year
    best_item: Optional[dict] = None
    best_score = -1

    for item in items:
        score = 0
        item_title = item.get("title") or ""
        norm_item_title = normalize_title(item_title)
        if target_title and norm_item_title == target_title:
            score += 6
        elif target_title and (target_title in norm_item_title or norm_item_title in target_title):
            score += 4

        item_year = item.get("publication_year")
        if target_year and item_year and int(item_year) == int(target_year):
            score += 3

        source_name = _safe_strip((item.get("primary_location") or {}).get("source", {}).get("display_name"))
        if record.journal and source_name and record.journal.lower().strip() == source_name.lower().strip():
            score += 2

        if score > best_score:
            best_score = score
            best_item = item

    return best_item if best_score >= 4 else None


def parse_openalex_orcids(item: dict) -> List[str]:
    result = []
    for authorship in item.get("authorships") or []:
        author_id = _safe_strip((authorship.get("author") or {}).get("id"))
        orcid = _safe_strip((authorship.get("author") or {}).get("orcid"))
        if orcid:
            result.append(orcid)
        elif author_id and "orcid.org" in author_id.lower():
            result.append(author_id)
    return sorted(set(result))


def parse_openalex_rors(item: dict) -> List[str]:
    rors = []
    for authorship in item.get("authorships") or []:
        for institution in authorship.get("institutions") or []:
            ror = _safe_strip(institution.get("ror"))
            if ror:
                rors.append(ror)
    return sorted(set(rors))


def parse_openalex_links(item: dict) -> Dict[str, Optional[str]]:
    links: Dict[str, Optional[str]] = {}
    doi = item.get("doi")
    if doi:
        links["doi_url"] = doi
    ids = item.get("ids") or {}
    openalex_id = ids.get("openalex") or item.get("id")
    if openalex_id:
        links["openalex_url"] = openalex_id
    best_oa = item.get("best_oa_location") or {}
    primary = item.get("primary_location") or {}
    pdf_url = best_oa.get("pdf_url") or primary.get("pdf_url")
    landing_url = best_oa.get("landing_page_url") or primary.get("landing_page_url")
    source_url = primary.get("source", {}).get("host_organization_lineage_names")
    if pdf_url:
        links["pdf_url"] = pdf_url
    if landing_url:
        links["publisher_url"] = landing_url
    if source_url and isinstance(source_url, list) and source_url:
        links["source_org_names"] = "; ".join(source_url)
    return links


# ---------- Enrichment ----------

def merge_links(base: Dict[str, Optional[str]], new: Dict[str, Optional[str]]) -> Dict[str, Optional[str]]:
    merged = dict(base or {})
    for key, value in (new or {}).items():
        if value and not merged.get(key):
            merged[key] = value
    return merged


async def enrich_one_record(client: httpx.AsyncClient, record: InputRecord, request: EnrichRequest) -> Tuple[Dict[str, Any], Dict[str, int], List[str]]:
    notes: List[str] = []
    hit_counts = {"crossref_hits": 0, "openalex_hits": 0}

    enriched: Dict[str, Any] = record.model_dump()
    enriched.update(
        {
            "publisher": None,
            "license": None,
            "funding": [],
            "orcid": [],
            "ror": [],
            "cited_by_count": None,
            "work_type": None,
            "source_journal": None,
            "is_open_access": None,
            "has_fulltext": None,
            "is_retracted_or_corrected": None,
            "notes": [],
        }
    )

    crossref_item = None
    doi = normalize_doi(record.doi)
    if doi:
        try:
            crossref_item = await crossref_lookup_by_doi(client, doi)
            if crossref_item:
                hit_counts["crossref_hits"] += 1
        except Exception as exc:
            notes.append(f"Crossref DOI lookup failed: {exc}")
    if not crossref_item:
        try:
            crossref_item = await crossref_search_by_metadata(client, record)
            if crossref_item:
                hit_counts["crossref_hits"] += 1
        except Exception as exc:
            notes.append(f"Crossref metadata search failed: {exc}")

    if crossref_item:
        crossref_doi = normalize_doi(crossref_item.get("DOI"))
        if request.fill_missing_doi and not enriched.get("doi") and crossref_doi:
            enriched["doi"] = crossref_doi
        if request.fill_publisher and not enriched.get("publisher"):
            enriched["publisher"] = _safe_strip(crossref_item.get("publisher"))
        if request.fill_license and not enriched.get("license"):
            enriched["license"] = parse_crossref_license(crossref_item)
        if request.fill_funding:
            enriched["funding"] = parse_crossref_funding(crossref_item)
        if request.fill_orcid_ror:
            enriched["orcid"] = parse_crossref_orcids(crossref_item)
        if request.check_updates_or_retractions:
            enriched["is_retracted_or_corrected"] = parse_crossref_retraction_flag(crossref_item)
        enriched["links"] = merge_links(enriched.get("links", {}), parse_crossref_links(crossref_item))

    openalex_item = None
    effective_doi = normalize_doi(enriched.get("doi"))
    if effective_doi:
        try:
            openalex_item = await openalex_lookup_by_doi(client, effective_doi)
            if openalex_item:
                hit_counts["openalex_hits"] += 1
        except Exception as exc:
            notes.append(f"OpenAlex DOI lookup failed: {exc}")
    if not openalex_item:
        try:
            openalex_item = await openalex_search_by_metadata(client, record)
            if openalex_item:
                hit_counts["openalex_hits"] += 1
        except Exception as exc:
            notes.append(f"OpenAlex metadata search failed: {exc}")

    if openalex_item:
        oa_doi = normalize_doi(openalex_item.get("doi"))
        if request.fill_missing_doi and not enriched.get("doi") and oa_doi:
            enriched["doi"] = oa_doi
        if request.fill_citation_metrics:
            enriched["cited_by_count"] = openalex_item.get("cited_by_count")
        enriched["work_type"] = _safe_strip(openalex_item.get("type"))
        source_name = _safe_strip((openalex_item.get("primary_location") or {}).get("source", {}).get("display_name"))
        if source_name:
            enriched["source_journal"] = source_name
            if not enriched.get("journal"):
                enriched["journal"] = source_name
        if request.fill_open_access_flags:
            is_oa = (openalex_item.get("open_access") or {}).get("is_oa")
            enriched["is_open_access"] = bool(is_oa) if is_oa is not None else None
            has_fulltext = openalex_item.get("has_fulltext")
            enriched["has_fulltext"] = bool(has_fulltext) if has_fulltext is not None else None
            if enriched["is_open_access"]:
                enriched["access_status"] = "open_access"
        if request.fill_orcid_ror:
            enriched["orcid"] = sorted(set(enriched.get("orcid", []) + parse_openalex_orcids(openalex_item)))
            enriched["ror"] = parse_openalex_rors(openalex_item)
        enriched["links"] = merge_links(enriched.get("links", {}), parse_openalex_links(openalex_item))

    if not enriched.get("access_status"):
        if enriched.get("is_open_access"):
            enriched["access_status"] = "open_access"
        elif enriched.get("abstract"):
            enriched["access_status"] = "abstract_only"
        else:
            enriched["access_status"] = "metadata_only"

    enriched["notes"] = notes
    return enriched, hit_counts, notes


@app.get("/health")
def health() -> Dict[str, Any]:
    return {"ok": True, "version": APP_VERSION, "service": APP_TITLE}


@app.post("/enrich", response_model=EnrichResponse)
async def enrich_literature_records(request: EnrichRequest) -> EnrichResponse:
    response_notes: List[str] = []
    source_counts = {"crossref_hits": 0, "openalex_hits": 0}
    output_records: List[EnrichedRecord] = []

    timeout = httpx.Timeout(HTTP_TIMEOUT)
    async with httpx.AsyncClient(timeout=timeout) as client:
        for record in request.records:
            enriched_record, hit_counts, notes = await enrich_one_record(client, record, request)
            source_counts["crossref_hits"] += hit_counts["crossref_hits"]
            source_counts["openalex_hits"] += hit_counts["openalex_hits"]
            if notes:
                response_notes.extend([f"{record.record_id}: {n}" for n in notes])
            output_records.append(EnrichedRecord(**enriched_record))

    return EnrichResponse(
        enrichment_id=f"enr_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}",
        enriched_at=datetime.utcnow().isoformat() + "Z",
        source_counts=source_counts,
        notes=response_notes,
        records=output_records,
    )
