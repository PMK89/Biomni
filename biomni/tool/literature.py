import os
import json
import re
import time
from io import BytesIO
from pathlib import Path
from urllib.parse import quote, urljoin

import requests
from bs4 import BeautifulSoup
try:
    from googlesearch import search
except Exception:  # pragma: no cover
    search = None
try:
    import PyPDF2
except Exception:  # pragma: no cover
    PyPDF2 = None
try:
    from pymed import PubMed
except Exception:  # pragma: no cover
    PubMed = None


def _resolve_papers_output_dir(output_dir: str | None) -> str:
    chat_dir = os.environ.get("BIOMNI_CHAT_DIR")
    if output_dir:
        if chat_dir:
            try:
                if Path(output_dir).resolve() == Path(chat_dir).resolve():
                    return str(Path(chat_dir) / "literature")
            except Exception:
                pass
        return output_dir

    if chat_dir:
        return str(Path(chat_dir) / "literature")
    return "literature"


def _normalize_pmid(pmid: str | None) -> str | None:
    if not pmid:
        return None
    s = str(pmid)
    m = re.search(r"\b\d{6,9}\b", s)
    return m.group(0) if m else None


def _normalize_authors(authors: object | None) -> list[str]:
    if not authors:
        return []
    if isinstance(authors, str):
        parts = [p.strip() for p in re.split(r"\s*;\s*|\s*,\s*", authors) if p.strip()]
        return parts if len(parts) > 1 else [authors]
    if isinstance(authors, (list, tuple)):
        names: list[str] = []
        for entry in authors:
            if not entry:
                continue
            if isinstance(entry, str):
                names.append(entry)
                continue
            if isinstance(entry, dict):
                last = entry.get("lastname") or entry.get("last_name") or entry.get("surname")
                first = entry.get("firstname") or entry.get("first_name") or entry.get("forename")
                name = entry.get("name") or entry.get("fullName") or entry.get("collective_name")
                if not name and (first or last):
                    name = " ".join(p for p in (first, last) if p)
                names.append(name or str(entry))
                continue
            last = getattr(entry, "lastname", None) or getattr(entry, "last_name", None)
            first = getattr(entry, "firstname", None) or getattr(entry, "first_name", None)
            name = getattr(entry, "name", None) or getattr(entry, "fullName", None)
            if not name and (first or last):
                name = " ".join(p for p in (first, last) if p)
            names.append(name or str(entry))
        return [n for n in names if n]
    return [str(authors)]


def _clean_text(value: object | None) -> str | None:
    if not value:
        return None
    if isinstance(value, (list, tuple)):
        value = "\n".join(str(v) for v in value if v)
    text = str(value)
    try:
        text = BeautifulSoup(text, "html.parser").get_text(" ", strip=True)
    except Exception:
        pass
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def _extract_year(value: object | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 1500 < value < 3000 else None
    if isinstance(value, float):
        year = int(value)
        return year if 1500 < year < 3000 else None
    if hasattr(value, "year"):
        try:
            year = int(getattr(value, "year"))
            return year if 1500 < year < 3000 else None
        except Exception:
            pass
    if isinstance(value, dict):
        for key in ("year", "pubYear", "pub_year", "publication_year", "publicationYear"):
            year = _extract_year(value.get(key))
            if year:
                return year
    text = str(value)
    match = re.search(r"\b(19|20)\d{2}\b", text)
    if match:
        return int(match.group(0))
    return None


def _write_pdf_text_dump(
    pdf_path: str,
    metadata: dict | None = None,
    max_chars: int = 200000,
) -> str | None:
    if PyPDF2 is None:
        return None
    try:
        path = Path(pdf_path)
        txt_path = path.with_suffix(".txt")
        if txt_path.exists():
            return str(txt_path)

        with open(path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            parts: list[str] = []
            total = 0
            for page in reader.pages:
                try:
                    text = page.extract_text() or ""
                except Exception:
                    text = ""
                if not text:
                    continue
                parts.append(text)
                total += len(text)
                if total >= max_chars:
                    break

        if not parts:
            return None

        header_lines: list[str] = []
        if metadata:
            title = metadata.get("title") if isinstance(metadata, dict) else None
            doi = metadata.get("doi") if isinstance(metadata, dict) else None
            source = metadata.get("source") if isinstance(metadata, dict) else None
            if title:
                header_lines.append(f"Title: {title}")
            if doi:
                header_lines.append(f"DOI: {doi}")
            if source:
                header_lines.append(f"Source: {source}")

        content = "\n".join(header_lines + ([""] if header_lines else []) + parts)
        txt_path.write_text(content, encoding="utf-8")
        return str(txt_path)
    except Exception:
        return None


def _extract_doi_candidates(doi: str | None) -> list[str]:
    if not doi:
        return []
    s = str(doi)
    found = re.findall(r"10\.\d{4,9}/[^\s\"<>]+", s)
    cleaned: list[str] = []
    for d in found:
        dd = d.strip().rstrip(". ,;)")
        if dd and dd not in cleaned:
            cleaned.append(dd)
    if cleaned:
        return cleaned
    parts = re.split(r"[\s\n\r\t,;]+", s)
    for part in parts:
        part = (part or "").strip().rstrip(". ,;)")
        if part.startswith("10.") and "/" in part and part not in cleaned:
            cleaned.append(part)
    return cleaned


def _resolve_europepmc_metadata_from_pmid(pmid: str, timeout: int = 30) -> dict:
    try:
        resp = requests.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
            params={"query": f"EXT_ID:{pmid} AND SRC:MED", "format": "json", "pageSize": 1},
            timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        if resp.status_code != 200:
            return {"status": "error", "error": f"EuropePMC returned status {resp.status_code}"}
        payload = resp.json() if resp.content else {}
        results = ((payload.get("resultList") or {}).get("result") or [])
        if not results:
            return {"status": "error", "error": "EuropePMC returned no results"}
        r0 = results[0] if isinstance(results[0], dict) else {}
        pmcid = r0.get("pmcid")
        doi = r0.get("doi")
        title = r0.get("title")
        abstract = _clean_text(r0.get("abstractText"))
        journal = _clean_text(r0.get("journalTitle") or r0.get("journalTitleAbbrev") or r0.get("journal"))
        authors = _normalize_authors(r0.get("authorString") or (r0.get("authorList") or {}).get("author"))
        year = _extract_year(
            r0.get("pubYear")
            or r0.get("pubDate")
            or r0.get("firstPublicationDate")
            or r0.get("electronicPublicationDate")
        )

        pdf_url = None
        ft = (r0.get("fullTextUrlList") or {}).get("fullTextUrl") or []
        if isinstance(ft, list):
            for item in ft:
                if not isinstance(item, dict):
                    continue
                u = item.get("url")
                style = (item.get("documentStyle") or "").lower()
                avail = (item.get("availability") or "").lower()
                if not u:
                    continue
                if ("pdf" in style or str(u).lower().endswith(".pdf")) and (
                    "open" in avail or "free" in avail or not avail
                ):
                    pdf_url = u
                    break

        return {
            "status": "success",
            "pmcid": pmcid,
            "doi": doi,
            "title": title,
            "abstract": abstract,
            "journal": journal,
            "authors": authors,
            "year": year,
            "pdf_url": pdf_url,
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


def _resolve_pmc_pdf_url_from_pmid(
    pmid: str,
    timeout: int = 30,
    epmc: dict | None = None,
) -> tuple[str | None, str | None, str | None]:
    try:
        epmc = epmc or _resolve_europepmc_metadata_from_pmid(str(pmid), timeout=timeout)
        if epmc.get("status") == "success":
            pmcid = epmc.get("pmcid")
            pdf_url = epmc.get("pdf_url")
            if pmcid and pdf_url:
                return str(pmcid), str(pdf_url), None

        email = os.environ.get("PUBMED_EMAIL") or os.environ.get("UNPAYWALL_EMAIL") or "biomni@example.com"
        last_status: int | None = None
        resp = None
        for attempt in range(3):
            try:
                resp = requests.get(
                    "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/",
                    params={"ids": str(pmid), "format": "json", "tool": "Biomni", "email": email},
                    timeout=timeout,
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                last_status = resp.status_code
                if resp.status_code != 429:
                    break
            except Exception:
                resp = None
            time.sleep(0.8 * (2**attempt))

        if resp is None:
            return None, None, "NCBI idconv request failed"
        if resp.status_code != 200:
            if resp.status_code == 403:
                epmc_fallback = _resolve_europepmc_metadata_from_pmid(str(pmid), timeout=timeout)
                if epmc_fallback.get("status") == "success" and epmc_fallback.get("pmcid") and epmc_fallback.get("pdf_url"):
                    return str(epmc_fallback.get("pmcid")), str(epmc_fallback.get("pdf_url")), None
            return None, None, f"NCBI idconv returned status {resp.status_code if resp is not None else last_status}"
        payload = resp.json() if resp.content else {}
        records = payload.get("records") or []
        if not records or not isinstance(records, list):
            return None, None, "NCBI idconv returned no records"
        rec = records[0] if isinstance(records[0], dict) else {}
        pmcid = rec.get("pmcid")
        if not pmcid:
            return None, None, "No PMCID available"

        article_url = f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/"
        page = requests.get(article_url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
        if page.status_code == 200:
            soup = BeautifulSoup(page.content, "html.parser")
            for a in soup.find_all("a", href=True):
                href = a.get("href")
                if not href:
                    continue
                href_l = href.lower()
                if ".pdf" in href_l or ("pdf" in href_l and "download" in href_l):
                    return pmcid, urljoin(article_url, href), None

        pdf_index_url = f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/pdf/"
        pdf_index = requests.get(pdf_index_url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
        if pdf_index.status_code == 200:
            soup = BeautifulSoup(pdf_index.content, "html.parser")
            for a in soup.find_all("a", href=True):
                href = a.get("href")
                if not href:
                    continue
                href_l = href.lower()
                if href_l.endswith(".pdf") or ".pdf?" in href_l:
                    return pmcid, urljoin(pdf_index_url, href), None

        return pmcid, pdf_index_url, None
    except Exception as exc:
        return None, None, str(exc)


def fetch_supplementary_info_from_doi(doi: str, output_dir: str = "supplementary_info"):
    """Fetches supplementary information for a paper given its DOI and returns a research log.

    Args:
        doi: The paper DOI.
        output_dir: Directory to save supplementary files.

    Returns:
        dict: A dictionary containing a research log and the downloaded file paths.

    """
    research_log = []
    research_log.append(f"Starting process for DOI: {doi}")

    # CrossRef API to resolve DOI to a publisher page
    crossref_url = f"https://doi.org/{doi}"
    headers = {"User-Agent": "Mozilla/5.0"}
    response = requests.get(crossref_url, headers=headers)

    if response.status_code != 200:
        log_message = f"Failed to resolve DOI: {doi}. Status Code: {response.status_code}"
        research_log.append(log_message)
        return {"log": research_log, "files": []}

    publisher_url = response.url
    research_log.append(f"Resolved DOI to publisher page: {publisher_url}")

    # Fetch publisher page
    response = requests.get(publisher_url, headers=headers)
    if response.status_code != 200:
        log_message = f"Failed to access publisher page for DOI {doi}."
        research_log.append(log_message)
        return {"log": research_log, "files": []}

    # Parse page content
    soup = BeautifulSoup(response.content, "html.parser")
    supplementary_links = []

    # Look for supplementary materials by keywords or links
    for link in soup.find_all("a", href=True):
        href = link.get("href")
        text = link.get_text().lower()
        if "supplementary" in text or "supplemental" in text or "appendix" in text:
            full_url = urljoin(publisher_url, href)
            supplementary_links.append(full_url)
            research_log.append(f"Found supplementary material link: {full_url}")

    if not supplementary_links:
        log_message = f"No supplementary materials found for DOI {doi}."
        research_log.append(log_message)
        return research_log

    # Create output directory
    os.makedirs(output_dir, exist_ok=True)
    research_log.append(f"Created output directory: {output_dir}")

    # Download supplementary materials
    downloaded_files = []
    for link in supplementary_links:
        file_name = os.path.join(output_dir, link.split("/")[-1])
        file_response = requests.get(link, headers=headers)
        if file_response.status_code == 200:
            with open(file_name, "wb") as f:
                f.write(file_response.content)
            downloaded_files.append(file_name)
            research_log.append(f"Downloaded file: {file_name}")
        else:
            research_log.append(f"Failed to download file from {link}")

    if downloaded_files:
        research_log.append(f"Successfully downloaded {len(downloaded_files)} file(s).")
    else:
        research_log.append(f"No files could be downloaded for DOI {doi}.")

    return "\n".join(research_log)


def download_open_access_paper_pdf(
    doi: str | None = None,
    url: str | None = None,
    output_dir: str | None = None,
    filename: str | None = None,
    timeout: int = 60,
) -> dict:
    if not doi and not url:
        return {
            "status": "error",
            "error": "Provide either doi or url",
        }

    base_dir = _resolve_papers_output_dir(output_dir)

    Path(base_dir).mkdir(parents=True, exist_ok=True)

    pdf_url = url
    metadata: dict = {}

    if doi and not pdf_url:
        doi_candidates = _extract_doi_candidates(doi)
        doi_clean = (doi_candidates[0] if doi_candidates else str(doi).splitlines()[0]).strip().rstrip(". ,;)")
        metadata = {"doi": doi_clean}

        # Attempt 1: Unpaywall (requires a real user email; 422 if missing/invalid)
        email = os.environ.get("UNPAYWALL_EMAIL")
        if email:
            unpaywall = f"https://api.unpaywall.org/v2/{doi_clean}"
            try:
                resp = requests.get(unpaywall, params={"email": email}, timeout=timeout)
            except Exception as exc:
                resp = None
                metadata["unpaywall_error"] = f"Failed to query Unpaywall: {exc}"

            if resp is not None and resp.status_code == 200:
                try:
                    data = resp.json()
                    metadata.update(
                        {
                            "title": data.get("title"),
                            "is_oa": data.get("is_oa"),
                            "best_oa_location": data.get("best_oa_location"),
                            "source": "unpaywall",
                        }
                    )
                    best = (data.get("best_oa_location") or {})
                    pdf_url = best.get("url_for_pdf") or best.get("url")
                except Exception as exc:
                    metadata["unpaywall_error"] = f"Failed to parse Unpaywall JSON: {exc}"
            elif resp is not None and resp.status_code == 422:
                metadata["unpaywall_error"] = "Unpaywall requires your own email address; set UNPAYWALL_EMAIL. Falling back to other resolvers."
            elif resp is not None and resp.status_code not in (200, 422):
                metadata["unpaywall_error"] = f"Unpaywall returned status {resp.status_code}"

        # Attempt 2: Semantic Scholar openAccessPdf (no auth)
        if not pdf_url:
            s2_doi = quote(doi_clean, safe="")
            s2_url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{s2_doi}"
            try:
                resp = requests.get(
                    s2_url,
                    params={"fields": "title,openAccessPdf"},
                    timeout=timeout,
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                if resp.status_code == 200:
                    data = resp.json() if resp.content else {}
                    metadata.setdefault("title", data.get("title"))
                    oa = data.get("openAccessPdf") or {}
                    pdf_url = oa.get("url")
                    if pdf_url:
                        metadata["source"] = "semanticscholar"
            except Exception as exc:
                metadata["semanticscholar_error"] = f"Failed to query Semantic Scholar: {exc}"

        # Attempt 3: Try DOI landing page and scrape PDF links
        if not pdf_url:
            try:
                landing = requests.get(
                    f"https://doi.org/{doi_clean}",
                    headers={"User-Agent": "Mozilla/5.0", "Accept": "text/html,application/xhtml+xml"},
                    timeout=timeout,
                    allow_redirects=True,
                )
                if landing.status_code == 200:
                    soup = BeautifulSoup(landing.content, "html.parser")
                    links = []
                    for a in soup.find_all("a", href=True):
                        href = a.get("href")
                        if not href:
                            continue
                        href_l = href.lower()
                        if ".pdf" in href_l or href_l.endswith("/pdf") or "/pdf?" in href_l or ("pdf" in href_l and "download" in href_l):
                            links.append(urljoin(landing.url, href))
                    if not links:
                        html = landing.text or ""
                        matches = re.findall(r"https?://[^\"\']+(?:\\.pdf|/pdf(?:\?[^\"\']*)?)", html, flags=re.IGNORECASE)
                        links.extend(matches[:3])
                    if links:
                        pdf_url = links[0]
                        metadata["source"] = "doi_landing_page"
            except Exception as exc:
                metadata["landing_page_error"] = f"Failed to resolve DOI landing page: {exc}"

        if not pdf_url:
            hint = "If you know a direct PDF URL, pass it via url=. Otherwise set UNPAYWALL_EMAIL and retry."
            if email:
                hint = "If you know a direct PDF URL, pass it via url=. Unpaywall was queried but did not return an open-access PDF."
            return {
                "status": "error",
                "error": "No open-access PDF URL could be resolved for DOI",
                "metadata": metadata,
                "hint": hint,
            }

    if not filename:
        safe = None
        if metadata.get("title"):
            safe = metadata["title"].lower()
        elif doi:
            safe = doi.lower()
        else:
            safe = "paper"
        safe = re.sub(r"[^a-z0-9\-_]+", "_", safe).strip("_")
        safe = safe[:120] if safe else "paper"
        filename = f"{safe}.pdf"

    out_path = str((Path(base_dir) / filename).resolve())

    if os.path.exists(out_path):
        stem = Path(out_path).stem
        suffix = Path(out_path).suffix
        parent = Path(out_path).parent
        for i in range(2, 1000):
            candidate = str((parent / f"{stem}__{i}{suffix}").resolve())
            if not os.path.exists(candidate):
                out_path = candidate
                break

    r = None
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            r = requests.get(pdf_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout)
            last_exc = None
            break
        except Exception as exc:
            last_exc = exc
            time.sleep(0.8 * (2**attempt))

    if r is None:
        return {
            "status": "error",
            "error": f"Failed to download PDF: {last_exc}",
            "url": pdf_url,
        }

    if r.status_code != 200:
        return {
            "status": "error",
            "error": f"PDF download returned status {r.status_code}",
            "url": pdf_url,
            "response_headers": dict(r.headers),
        }

    content_type = (r.headers.get("Content-Type") or "").lower()
    if "pdf" not in content_type and not r.content.startswith(b"%PDF"):
        # PMC sometimes serves an HTML index at /pdf/; try to scrape the real PDF link once.
        if pdf_url and "pmc.ncbi.nlm.nih.gov" in str(pdf_url) and "/pdf" in str(pdf_url) and r.content:
            try:
                soup = BeautifulSoup(r.content, "html.parser")
                hrefs: list[str] = []
                for a in soup.find_all("a", href=True):
                    href = a.get("href")
                    if not href:
                        continue
                    href_l = href.lower()
                    if href_l.endswith(".pdf") or ".pdf?" in href_l:
                        hrefs.append(urljoin(str(pdf_url), href))
                if hrefs:
                    pdf_url = hrefs[0]
                    r2 = requests.get(pdf_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout)
                    content_type2 = (r2.headers.get("Content-Type") or "").lower()
                    if r2.status_code == 200 and ("pdf" in content_type2 or r2.content.startswith(b"%PDF")):
                        with open(out_path, "wb") as f:
                            f.write(r2.content)
                        metadata_with_fallback = {**metadata, "pmc_html_fallback": True}
                        text_path = _write_pdf_text_dump(out_path, metadata_with_fallback)
                        return {
                            "status": "success",
                            "file_path": out_path,
                            "text_path": text_path,
                            "url": pdf_url,
                            "metadata": metadata_with_fallback,
                        }
            except Exception:
                pass

        return {
            "status": "error",
            "error": "URL did not return a PDF document",
            "url": pdf_url,
            "content_type": content_type,
        }

    with open(out_path, "wb") as f:
        f.write(r.content)

    text_path = _write_pdf_text_dump(out_path, metadata)

    return {
        "status": "success",
        "file_path": out_path,
        "text_path": text_path,
        "url": pdf_url,
        "metadata": metadata,
    }


def query_arxiv(query: str, max_papers: int = 10) -> str:
    """Query arXiv for papers based on the provided search query.

    Parameters
    ----------
    - query (str): The search query string.
    - max_papers (int): The maximum number of papers to retrieve (default: 10).

    Returns
    -------
    - str: The formatted search results or an error message.

    """
    import arxiv

    try:
        client = arxiv.Client()
        search = arxiv.Search(query=query, max_results=max_papers, sort_by=arxiv.SortCriterion.Relevance)
        results = "\n\n".join([f"Title: {paper.title}\nSummary: {paper.summary}" for paper in client.results(search)])
        return results if results else "No papers found on arXiv."
    except Exception as e:
        return f"Error querying arXiv: {e}"


def query_scholar(query: str) -> str:
    """Query Google Scholar for papers based on the provided search query.

    Parameters
    ----------
    - query (str): The search query string.

    Returns
    -------
    - str: The first search result formatted or an error message.

    """
    from scholarly import ProxyGenerator, scholarly

    # Set up a ProxyGenerator object to use free proxies
    # This needs to be done only once per session
    pg = ProxyGenerator()
    pg.FreeProxies()
    scholarly.use_proxy(pg)
    try:
        search_query = scholarly.search_pubs(query)
        result = next(search_query, None)
        if result:
            return f"Title: {result['bib']['title']}\nYear: {result['bib']['pub_year']}\nVenue: {result['bib']['venue']}\nAbstract: {result['bib']['abstract']}"
        else:
            return "No results found on Google Scholar."
    except Exception as e:
        return f"Error querying Google Scholar: {e}"


def query_pubmed(
    query: str,
    max_papers: int = 10,
    max_retries: int = 3,
    retmax: int | None = None,
) -> dict:
    """Query PubMed for papers based on the provided search query.

    Parameters
    ----------
    - query (str): The search query string.
    - max_papers (int): The maximum number of papers to retrieve (default: 10).
    - max_retries (int): Maximum number of retry attempts with modified queries (default: 3).

    Returns
    -------
    - str: The formatted search results or an error message.

    """
    try:
        if PubMed is None:
            return {
                "status": "error",
                "error": "missing optional dependency 'pymed' (pip install pymed)",
                "query": query,
                "papers": [],
                "pmids": [],
            }
        email = os.environ.get("PUBMED_EMAIL") or os.environ.get("UNPAYWALL_EMAIL") or "biomni@example.com"
        pubmed = PubMed(tool="Biomni", email=email)

        if isinstance(retmax, int) and retmax > 0:
            max_papers = retmax

        # Initial attempt
        papers = list(pubmed.query(query, max_results=max_papers))

        # Retry with modified queries if no results
        retries = 0
        while not papers and retries < max_retries:
            retries += 1
            # Simplify query with each retry by removing the last word
            simplified_query = " ".join(query.split()[:-retries]) if len(query.split()) > retries else query
            time.sleep(1)  # Add delay between requests
            papers = list(pubmed.query(simplified_query, max_results=max_papers))

        if papers:
            out = []
            pmids: list[str] = []
            for paper in papers:
                pmid_raw = getattr(paper, "pubmed_id", None) or getattr(paper, "pmid", None)
                pmid = _normalize_pmid(str(pmid_raw)) if pmid_raw else None
                doi_raw = getattr(paper, "doi", None)
                doi = None
                if doi_raw:
                    doi_cands = _extract_doi_candidates(str(doi_raw))
                    doi = doi_cands[0] if doi_cands else str(doi_raw).splitlines()[0].strip()
                if not doi:
                    try:
                        d = paper.toDict() if hasattr(paper, "toDict") else {}
                        doi_any = d.get("doi") or d.get("DOI")
                        doi_cands = _extract_doi_candidates(str(doi_any)) if doi_any else []
                        doi = doi_cands[0] if doi_cands else doi_any
                        if not doi:
                            ids = d.get("identifier") or {}
                            if isinstance(ids, dict):
                                doi_any = ids.get("doi") or ids.get("DOI")
                                doi_cands = _extract_doi_candidates(str(doi_any)) if doi_any else []
                                doi = doi_cands[0] if doi_cands else doi_any
                    except Exception:
                        doi = None
                title = _clean_text(getattr(paper, "title", None))
                journal = _clean_text(getattr(paper, "journal", None))
                abstract = _clean_text(getattr(paper, "abstract", None))
                authors = _normalize_authors(getattr(paper, "authors", None))
                year = _extract_year(
                    getattr(paper, "publication_date", None)
                    or getattr(paper, "publication_year", None)
                    or getattr(paper, "year", None)
                )
                try:
                    d = paper.toDict() if hasattr(paper, "toDict") else {}
                    if not abstract:
                        abstract = _clean_text(d.get("abstract"))
                    if not journal:
                        journal = _clean_text(d.get("journal"))
                    if not authors:
                        authors = _normalize_authors(
                            d.get("authors") or (d.get("authorList") or {}).get("author") or d.get("author_string")
                        )
                    if not year:
                        year = _extract_year(d.get("publication_date") or d.get("pub_date") or d.get("year"))
                except Exception:
                    pass
                url = getattr(paper, "url", None)
                item = {
                    "title": title,
                    "journal": journal,
                    "abstract": abstract,
                    "authors": authors,
                    "year": year,
                    "pmid": pmid,
                    "doi": doi,
                    "url": url,
                }
                out.append(item)
                if pmid:
                    pmids.append(str(pmid))
            return {
                "status": "success",
                "query": query,
                "papers": out,
                "pmids": pmids,
                "count": len(out),
            }
        else:
            return {
                "status": "success",
                "query": query,
                "papers": [],
                "pmids": [],
                "count": 0,
                "message": "No papers found on PubMed after multiple query attempts.",
            }
    except Exception as e:
        return {
            "status": "error",
            "error": f"Error querying PubMed: {e}",
            "query": query,
            "papers": [],
            "pmids": [],
        }


def download_pubmed_open_access_pdfs(
    query: str = None,
    pmids: list = None,
    max_papers: int = 10,
    output_dir: str = "./papers",
    timeout: int = 60,
) -> dict:
    """Downloads open-access PDFs from PubMed results."""
    if not query and not pmids:
        return {
            "status": "error",
            "error": "Provide either query or pmids",
            "downloaded": [],
            "skipped": [],
            "errors": [],
            "count": {"downloaded": 0, "skipped": 0, "errors": 0},
        }

    def _scrape_doi_from_pubmed_page(_pmid: str) -> list[str]:
        try:
            u = f"https://pubmed.ncbi.nlm.nih.gov/{str(_pmid).strip().splitlines()[0].strip().rstrip('/')}/"
            resp = requests.get(
                u,
                timeout=timeout,
                headers={"User-Agent": "Mozilla/5.0", "Accept": "text/html,application/xhtml+xml"},
            )
            if resp.status_code != 200:
                return []
            soup = BeautifulSoup(resp.content, "html.parser")
            for name in ("citation_doi", "dc.identifier", "DC.Identifier"):
                m = soup.find("meta", attrs={"name": name})
                if m and m.get("content"):
                    cands = _extract_doi_candidates(m.get("content"))
                    if cands:
                        return cands

            for a in soup.find_all("a", href=True):
                href = a.get("href")
                if not href:
                    continue
                href_l = href.lower()
                if "doi.org" in href_l or "doi.org/10." in href_l:
                    cands = _extract_doi_candidates(href)
                    if cands:
                        return cands
            html = resp.text or ""
            m2 = re.search(r"\bdoi\s*[:]\s*(10\.\d{4,9}/[^\s\"<>]+)", html, flags=re.IGNORECASE)
            if m2:
                return _extract_doi_candidates(m2.group(1))

            # Last resort: extract any DOI-like pattern from the HTML.
            cands = _extract_doi_candidates(html)
            return cands[:5] if cands else []
        except Exception:
            return []

    pubmed = None
    if PubMed is not None:
        email = os.environ.get("PUBMED_EMAIL") or os.environ.get("UNPAYWALL_EMAIL") or "biomni@example.com"
        pubmed = PubMed(tool="Biomni", email=email)

    if pmids:
        resolved: list[object] = []
        for pmid in pmids[:max_papers]:
            if pubmed is None:
                resolved.append({"_pmid": str(pmid), "_pmid_only": True})
                continue
            try:
                hits = list(pubmed.query(f"{pmid}[PMID]", max_results=1))
            except Exception as exc:
                hits = []
                resolved.append({"_pmid": pmid, "_error": str(exc)})
            if hits:
                resolved.append(hits[0])
        papers = resolved
    else:
        if pubmed is None:
            return {
                "status": "error",
                "error": "missing optional dependency 'pymed' (pip install pymed) for query-based PubMed search; provide pmids= instead",
                "downloaded": [],
                "skipped": [],
                "errors": [],
                "count": {"downloaded": 0, "skipped": 0, "errors": 0},
            }
        papers = list(pubmed.query(str(query), max_results=max_papers))
    downloaded = []
    skipped = []
    errors = []

    resolved_output_dir = _resolve_papers_output_dir(output_dir)
    Path(resolved_output_dir).mkdir(parents=True, exist_ok=True)

    papers_meta: list[dict] = []

    seen: set[tuple[str | None, str | None]] = set()

    def _write_missing_pdf_markdown(
        *,
        title: str | None,
        pmid: str | None,
        doi: str | None,
        doi_candidates: list[str],
        url: str | None,
        pmcid: str | None,
        pmc_pdf_url: str | None,
        reason: str | None,
        error: dict | None,
        authors: list[str] | None,
        journal: str | None,
        year: int | None,
        abstract: str | None,
    ) -> str | None:
        base = title or doi or (f"pmid_{pmid}" if pmid else "paper")
        safe = re.sub(r"[^a-z0-9\-_]+", "_", (base or "paper").lower()).strip("_")
        if pmid:
            safe = f"{safe}_pmid_{pmid}" if safe else f"pmid_{pmid}"
        safe = safe[:120] if safe else "paper"

        md_path = Path(resolved_output_dir) / f"{safe}.md"
        if md_path.exists():
            stem = md_path.stem
            suffix = md_path.suffix
            for i in range(2, 1000):
                candidate = md_path.with_name(f"{stem}__{i}{suffix}")
                if not candidate.exists():
                    md_path = candidate
                    break

        abstract_text = _clean_text(abstract)
        lines = [f"# {title or 'Untitled paper'}", ""]
        if pmid:
            lines.append(f"- PMID: {pmid}")
        if doi:
            lines.append(f"- DOI: {doi}")
        if doi_candidates:
            lines.append(f"- DOI candidates: {', '.join(doi_candidates[:10])}")
        if journal:
            lines.append(f"- Journal: {journal}")
        if year:
            lines.append(f"- Year: {year}")
        if authors:
            author_list = ", ".join(authors[:20])
            suffix = " ..." if len(authors) > 20 else ""
            lines.append(f"- Authors: {author_list}{suffix}")
        if pmcid:
            lines.append(f"- PMCID: {pmcid}")
        if url:
            lines.append(f"- PubMed URL: {url}")
        if pmc_pdf_url:
            lines.append(f"- PMC PDF URL: {pmc_pdf_url}")
        lines.append("")
        lines.append("## Abstract")
        if abstract_text:
            lines.append(abstract_text)
        else:
            lines.append("(not available)")
        lines.append("")
        lines.append("## PDF status")
        lines.append(f"- Status: not available")
        if reason:
            lines.append(f"- Reason: {reason}")
        if error:
            lines.append("- Error details:")
            lines.append("```json")
            lines.append(json.dumps(error, ensure_ascii=False, indent=2))
            lines.append("```")
        lines.append("")
        lines.append("## Notes")
        lines.append("PDF could not be downloaded automatically. This summary preserves citation metadata for manual review.")

        try:
            md_path.write_text("\n".join(lines), encoding="utf-8")
            return str(md_path)
        except Exception:
            return None

    for paper in papers:
        if isinstance(paper, dict) and paper.get("_error"):
            errors.append({"pmid": paper.get("_pmid"), "error": paper.get("_error")})
            continue

        pmid_raw = None
        if isinstance(paper, dict) and paper.get("_pmid_only"):
            pmid_raw = paper.get("_pmid")
        else:
            pmid_raw = getattr(paper, "pubmed_id", None) or getattr(paper, "pmid", None)
        pmid = _normalize_pmid(str(pmid_raw)) if pmid_raw else None
        doi = getattr(paper, "doi", None)
        if not doi:
            try:
                d = paper.toDict() if hasattr(paper, "toDict") else {}
                doi = d.get("doi") or d.get("DOI")
                if not doi:
                    ids = d.get("identifier") or {}
                    if isinstance(ids, dict):
                        doi = ids.get("doi") or ids.get("DOI")
            except Exception:
                doi = None

        doi_candidates = _extract_doi_candidates(doi)

        title = _clean_text(getattr(paper, "title", None))
        abstract = _clean_text(getattr(paper, "abstract", None))
        journal = _clean_text(getattr(paper, "journal", None))
        authors = _normalize_authors(getattr(paper, "authors", None))
        year = _extract_year(
            getattr(paper, "publication_date", None)
            or getattr(paper, "publication_year", None)
            or getattr(paper, "year", None)
        )
        try:
            d = paper.toDict() if hasattr(paper, "toDict") else {}
            if not abstract:
                abstract = _clean_text(d.get("abstract"))
            if not journal:
                journal = _clean_text(d.get("journal"))
            if not authors:
                authors = _normalize_authors(
                    d.get("authors") or (d.get("authorList") or {}).get("author") or d.get("author_string")
                )
            if not year:
                year = _extract_year(d.get("publication_date") or d.get("pub_date") or d.get("year"))
        except Exception:
            pass

        epmc = None
        if pmid and (not doi_candidates or not title or not abstract or not journal or not authors or not year):
            epmc = _resolve_europepmc_metadata_from_pmid(str(pmid), timeout=timeout)
            if epmc.get("status") == "success":
                if not title:
                    title = epmc.get("title")
                if not abstract:
                    abstract = epmc.get("abstract")
                if not journal:
                    journal = epmc.get("journal")
                if not authors:
                    authors = epmc.get("authors") or []
                if not year:
                    year = epmc.get("year")
                if not doi_candidates and epmc.get("doi"):
                    doi_candidates = _extract_doi_candidates(str(epmc.get("doi")))

        if pmid and not doi_candidates:
            doi_candidates = _scrape_doi_from_pubmed_page(str(pmid))
        url = None
        if pmid:
            url = f"https://pubmed.ncbi.nlm.nih.gov/{str(pmid).splitlines()[0].strip().split()[0].rstrip('/')}/"

        # Always try PMC first when we have a PMID (even if DOI exists)
        key = (pmid, doi_candidates[0] if doi_candidates else None)
        if key in seen:
            continue
        seen.add(key)

        downloaded_this = False

        meta_idx: int | None = None
        if pmid:
            pmcid, pmc_pdf_url, pmc_error = _resolve_pmc_pdf_url_from_pmid(str(pmid), timeout=timeout, epmc=epmc)
            if pmc_pdf_url:
                fn = f"{pmcid}.pdf" if pmcid else None
                res = download_open_access_paper_pdf(url=pmc_pdf_url, output_dir=resolved_output_dir, timeout=timeout, filename=fn)
                papers_meta.append(
                    {
                        "title": title,
                        "abstract": abstract,
                        "authors": authors,
                        "journal": journal,
                        "year": year,
                        "pmid": pmid,
                        "pmid_raw": str(pmid_raw) if pmid_raw is not None else None,
                        "doi": doi_candidates[0] if doi_candidates else None,
                        "doi_candidates": doi_candidates[:10] if doi_candidates else [],
                        "pmcid": pmcid,
                        "url": url,
                        "pmc_pdf_url": pmc_pdf_url,
                        "pmc_error": pmc_error,
                        "pmc_download": res,
                    }
                )
                meta_idx = len(papers_meta) - 1
                if res.get("status") == "success":
                    downloaded.append(res)
                    downloaded_this = True
                    continue
                errors.append({"pmid": pmid, "pmcid": pmcid, "error": res})
            else:
                # keep pmc_error in meta for debugging, but continue with DOI resolution
                papers_meta.append(
                    {
                        "title": title,
                        "abstract": abstract,
                        "authors": authors,
                        "journal": journal,
                        "year": year,
                        "pmid": pmid,
                        "pmid_raw": str(pmid_raw) if pmid_raw is not None else None,
                        "doi": doi_candidates[0] if doi_candidates else None,
                        "doi_candidates": doi_candidates[:10] if doi_candidates else [],
                        "pmcid": pmcid,
                        "url": url,
                        "pmc_pdf_url": pmc_pdf_url,
                        "pmc_error": pmc_error,
                    }
                )
                meta_idx = len(papers_meta) - 1

        if not doi_candidates:
            if pmid:
                skipped.append({"pmid": pmid, "reason": "no_doi_or_pmc"})
            else:
                skipped.append({"pmid": None, "reason": "no_doi_or_pmc"})
            _write_missing_pdf_markdown(
                title=title,
                pmid=pmid,
                doi=doi_candidates[0] if doi_candidates else None,
                doi_candidates=doi_candidates,
                url=url,
                pmcid=pmcid if pmid else None,
                pmc_pdf_url=None,
                reason="no_doi_or_pmc",
                error=None,
                authors=authors,
                journal=journal,
                year=year,
                abstract=abstract,
            )
            continue

        # If we reach here, we have DOI candidates and PMC did not succeed.
        # Keep DOI attempt info on the existing record when possible.
        if meta_idx is None:
            papers_meta.append(
                {
                    "title": title,
                    "abstract": abstract,
                    "authors": authors,
                    "journal": journal,
                    "year": year,
                    "pmid": pmid,
                    "pmid_raw": str(pmid_raw) if pmid_raw is not None else None,
                    "doi": doi_candidates[0],
                    "doi_candidates": doi_candidates[:10],
                    "pmcid": None,
                    "url": url,
                }
            )
            meta_idx = len(papers_meta) - 1
        else:
            papers_meta[meta_idx].setdefault("doi", doi_candidates[0])
            papers_meta[meta_idx].setdefault("doi_candidates", doi_candidates[:10])

        last_err: dict | None = None
        for cand in doi_candidates[:5]:
            res = download_open_access_paper_pdf(doi=str(cand), output_dir=resolved_output_dir, timeout=timeout)
            if res.get("status") == "success":
                downloaded.append(res)
                downloaded_this = True
                last_err = None
                break
            last_err = res
        if last_err is not None:
            errors.append({"pmid": pmid, "doi": doi_candidates[0], "error": last_err})
        if not downloaded_this:
            _write_missing_pdf_markdown(
                title=title,
                pmid=pmid,
                doi=doi_candidates[0] if doi_candidates else None,
                doi_candidates=doi_candidates,
                url=url,
                pmcid=pmcid if pmid else None,
                pmc_pdf_url=pmc_pdf_url if pmid else None,
                reason="pdf_unavailable",
                error=last_err,
                authors=authors,
                journal=journal,
                year=year,
                abstract=abstract,
            )

    report_path = str((Path(resolved_output_dir) / "pubmed_download_report.json").resolve())
    try:
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "query": query,
                    "pmids": pmids,
                    "max_papers": max_papers,
                    "papers": papers_meta,
                    "downloaded": downloaded,
                    "skipped": skipped,
                    "errors": errors,
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
    except Exception:
        report_path = None

    status = "success" if report_path else ("success" if downloaded else "error")

    return {
        "status": status,
        "report_path": report_path,
        "output_dir": str(Path(resolved_output_dir).resolve()),
        "downloaded": downloaded,
        "skipped": skipped,
        "errors": errors,
        "count": {"downloaded": len(downloaded), "skipped": len(skipped), "errors": len(errors)},
    }


def search_google(query: str, num_results: int = 3, language: str = "en") -> list[dict]:
    """Search using Google search.

    Args:
        query (str): The search query (e.g., "protocol text or seach question")
        num_results (int): Number of results to return (default: 10)
        language (str): Language code for search results (default: 'en')
        pause (float): Pause between searches to avoid rate limiting (default: 2.0 seconds)

    Returns:
        List[dict]: List of dictionaries containing search results with title and URL

    """
    if search is None:
        return [{"status": "error", "error": "missing optional dependency 'googlesearch'"}]
    try:
        results_string = ""
        search_query = f"{query}"

        print(f"Searching for {search_query} with {num_results} results and {language} language")

        results = []
        for res in search(search_query, num_results=num_results, lang=language, advanced=True):
            print(f"Found result: {res.title}")
            title = res.title
            url = res.url
            description = res.description

            results_string += f"Title: {title}\nURL: {url}\nDescription: {description}\n\n"

    except Exception as e:
        print(f"Error performing search: {str(e)}")
    return results_string


def advanced_web_search(
    query: str,
    max_searches: int = 3,
    max_retries: int = 3,
) -> str:
    """
    Initiate an advanced web search by launching a specialized agent to collect relevant information and citations through multiple rounds of web searches for a given query.

    Parameters
    ----------
    query : str
        The search phrase to look up.
    max_searches : int, optional
        Upper-bound on searches inside this request.
    max_retries : int, optional
        Maximum number of retry attempts.

    Returns
    -------
    str
        A formatted string containing the response and citations.
    """
    from biomni.llm import get_llm
    from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

    try:
        llm = get_llm()
    except Exception as e:
        return f"Error initializing LLM: {str(e)}"

    prompt = """You are a research assistant. Your goal is to answer the user's query by performing web searches.

TOOLS:
1. SEARCH: <query>
   - Use this to search the web.
   - Example: SEARCH: population of France
2. ANSWER: <text>
   - Use this to provide the final answer.
   - Example: ANSWER: The population of France is ...

INSTRUCTIONS:
- You can perform up to {max_searches} searches.
- After each search, you will receive the results.
- Always cite your sources in the ANSWER using the URLs provided in the search results.
- If you have enough information, output ANSWER: followed by your answer.
- Only output one action at a time.
"""

    messages = [
        SystemMessage(content=prompt.format(max_searches=max_searches)),
        HumanMessage(content=f"User Query: {query}")
    ]
    
    searches_performed = 0

    while searches_performed < max_searches:
        try:
            response = llm.invoke(messages)
            content = response.content.strip()
            messages.append(AIMessage(content=content))
            
            if content.startswith("SEARCH:"):
                search_query = content[7:].strip()
                # Use existing search_google function
                try:
                    search_results = search_google(search_query, num_results=3)
                except Exception as e:
                    search_results = f"Error performing search: {str(e)}"
                
                messages.append(HumanMessage(content=f"Search Results:\n{search_results}"))
                searches_performed += 1
            
            elif content.startswith("ANSWER:"):
                return content[7:].strip()
            
            else:
                # If the model didn't follow the format, treat it as an answer if it looks like one, 
                # or ask it to retry.
                # For robustness, if it contains "ANSWER:", extract it.
                if "ANSWER:" in content:
                    return content.split("ANSWER:", 1)[1].strip()
                
                # Fallback: return content
                return content

        except Exception as e:
             return f"Error during search execution: {str(e)}"

    # If we reached here, ask for final answer
    messages.append(HumanMessage(content="Please provide a final answer based on the information gathered so far."))
    final_response = llm.invoke(messages)
    return final_response.content


def advanced_web_search_claude(
    query: str,
    max_searches: int = 3,
    max_retries: int = 3,
) -> str:
    """
    Legacy alias for advanced_web_search, specific to Claude models if needed.
    
    Parameters
    ----------
    query : str
        The search phrase to look up.
    max_searches : int, optional
        Upper-bound on searches inside this request.
    max_retries : int, optional
        Maximum number of retry attempts.

    Returns
    -------
    str
        A formatted string containing the response and citations.
    """
    return advanced_web_search(query, max_searches, max_retries)




def extract_url_content(url: str) -> str:
    """Extract the text content of a webpage using requests and BeautifulSoup.

    Args:
        url: Webpage URL to extract content from

    Returns:
        Text content of the webpage

    """
    response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})

    # Check if the response is in text format
    if "text/plain" in response.headers.get("Content-Type", "") or "application/json" in response.headers.get(
        "Content-Type", ""
    ):
        return response.text.strip()  # Return plain text or JSON response directly

    # If it's HTML, use BeautifulSoup to parse
    soup = BeautifulSoup(response.text, "html.parser")

    # Try to find main content first, fallback to body
    content = soup.find("main") or soup.find("article") or soup.body

    # Remove unwanted elements
    for element in content(["script", "style", "nav", "header", "footer", "aside", "iframe"]):
        element.decompose()

    # Extract text with better formatting
    paragraphs = content.find_all(["p", "h1", "h2", "h3", "h4", "h5", "h6"])
    cleaned_text = []

    for p in paragraphs:
        text = p.get_text().strip()
        if text:  # Only add non-empty paragraphs
            cleaned_text.append(text)

    return "\n\n".join(cleaned_text)


def extract_pdf_content(url: str) -> str:
    """Extract the text content of a PDF file given its URL.

    Args:
        url: URL of the PDF file to extract text from

    Returns:
        The extracted text content from the PDF

    """
    try:
        # Check if the URL ends with .pdf
        if not url.lower().endswith(".pdf"):
            # If not, try to find a PDF link on the page
            response = requests.get(url, timeout=30)
            if response.status_code == 200:
                # Look for PDF links in the HTML content
                pdf_links = re.findall(r'href=[\'"]([^\'"]+\.pdf)[\'"]', response.text)
                if pdf_links:
                    # Use the first PDF link found
                    if not pdf_links[0].startswith("http"):
                        # Handle relative URLs
                        base_url = "/".join(url.split("/")[:3])
                        url = base_url + pdf_links[0] if pdf_links[0].startswith("/") else base_url + "/" + pdf_links[0]
                    else:
                        url = pdf_links[0]
                else:
                    return f"No PDF file found at {url}. Please provide a direct link to a PDF file."

        # Download the PDF
        response = requests.get(url, timeout=30)

        # Check if we actually got a PDF file (by checking content type or magic bytes)
        content_type = response.headers.get("Content-Type", "").lower()
        if "application/pdf" not in content_type and not response.content.startswith(b"%PDF"):
            return f"The URL did not return a valid PDF file. Content type: {content_type}"

        pdf_file = BytesIO(response.content)

        # Try with PyPDF2 first
        try:
            text = ""
            if PyPDF2 is None:
                return "PyPDF2 is not installed; cannot extract text from PDF. PDF download may still succeed."
            pdf_reader = PyPDF2.PdfReader(pdf_file)
            for page_num in range(len(pdf_reader.pages)):
                page = pdf_reader.pages[page_num]
                text += page.extract_text() + "\n\n"
        except Exception as e:
            print(f"Error extracting text from PDF: {str(e)}")

        # Clean up the text
        text = re.sub(r"\s+", " ", text).strip()

        if not text:
            return "The PDF file did not contain any extractable text. It may be an image-based PDF requiring OCR."

        return text

    except requests.exceptions.RequestException as e:
        return f"Error downloading PDF: {str(e)}"
    except Exception as e:
        return f"Error extracting text from PDF: {str(e)}"
