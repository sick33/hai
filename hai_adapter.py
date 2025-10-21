# adapter_min.py
from flask import Flask, request, jsonify
import pandas as pd
import os, requests
from dotenv import load_dotenv
##웹검색 라이브러리
import json, re
from urllib.parse import urlencode
try:
    from bs4 import BeautifulSoup  # optional
    _HAS_BS4 = True
except Exception:
    _HAS_BS4 = False

app = Flask(__name__)
EXCEL_PATH = os.getenv("HAI_EXCEL_PATH", "data/골드문_250819.xlsx")
# ===== demo data =====
PATIENTS = [
    {"id": "A123", "name": "Kim", "age": 43},
    {"id": "B456", "name": "Lee", "age": 37},
]

# ===== 직원데이터 =====
#df = pd.read_excel("data/골드문_250819.xlsx")   # 엑셀 파일 경로
#emp = df.loc[:7000].to_dict(orient="records")

# ===== 유틸: JSON-RPC 응답 헬퍼 =====
def ok(res, _id): 
    return jsonify({"jsonrpc":"2.0","result":res,"id":_id})

def err(code, msg, _id, data=None):
    e = {"code": code, "message": msg}
    if data is not None: e["data"] = data
    return jsonify({"jsonrpc":"2.0","error":e,"id":_id})

# ===== HAI 호출(옵션) =====
def call_hai_chat(messages, model=None, client_to_use=None, **kwargs):
    """
    HAI(OpenAI 스타일) /chat/completions 프록시
    - 환경변수 필요:
      HAI_BASE_URL=https://
      HAI_BEARER_TOKEN=...
      (필요시) HAI_X_API_KEY=...
      HAI_MODEL=Konan-LLM-ENT-11
    """
    load_dotenv(".env")  # 같은 디렉터리의 .env 자동 로드
    base = os.getenv("HAI_BASE_URL", "https://mhai.hallym.or.kr/open-api").rstrip("/")
    url  = base + "/chat/completions"
    token= os.getenv("HAI_BEARER_TOKEN","").strip()
    xkey = os.getenv("HAI_X_API_KEY","")
    model= model or os.getenv("HAI_MODEL","Konan-LLM-ENT-11")

    if not token:
        raise RuntimeError("HAI_BEARER_TOKEN is empty")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-API-KEY": xkey,  # 빈값도 헤더로 보냄(게이트웨이 요구 가능)
    }

    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        # 서버 라우팅 키가 필수이면 반드시 포함
        "client_to_use": client_to_use or "konanllm",
    }
    # 튜닝 파라미터 덮어쓰기
    payload.update(kwargs)

    r = requests.post(url, headers=headers, json=payload, timeout=30)
    r.raise_for_status()
    j = r.json()
    return j["choices"][0]["message"]["content"]

# ====== 웹검색: Provider 1) Brave Search API (권장, 유료/키 필요) ======
def search_brave(q: str, count: int = 10, safesearch: str = "moderate"):
    """
    https://api.search.brave.com/res/v1/web/search
    요구: 환경변수 BRAVE_API_KEY, 지역/언어 옵션은 필요 시 확장
    """
    load_dotenv(".env")
    api_key = os.getenv("BRAVE_API_KEY","").strip()
    if not api_key:
        raise RuntimeError("BRAVE_API_KEY not set")

    url = "https://api.search.brave.com/res/v1/web/search"
    params = {"q": q, "count": count, "safesearch": safesearch}
    headers = {"Accept":"application/json","X-Subscription-Token": api_key}
    r = requests.get(url, headers=headers, params=params, timeout=12)
    r.raise_for_status()
    j = r.json()

    rows = []
    for it in j.get("web", {}).get("results", []):
        rows.append({
            "title": it.get("title",""),
            "link": it.get("url",""),
            "snippet": it.get("description",""),
            "source": it.get("meta_url", {}).get("host",""),
        })
        if len(rows) >= count: break
    return {"provider":"brave","q":q,"rows":rows,"matched":len(rows)}

# ====== 웹검색: Provider 2) Bing Web Search (키 필요) ======
def search_bing(q: str, count: int = 10, mkt: str = "ko-KR", safesearch: str = "Moderate"):
    """
    https://api.bing.microsoft.com/v7.0/search
    요구: 환경변수 BING_API_KEY
    """
    load_dotenv(".env")
    api_key = os.getenv("BING_API_KEY","").strip()
    if not api_key:
        raise RuntimeError("BING_API_KEY not set")

    url = "https://api.bing.microsoft.com/v7.0/search"
    params = {"q": q, "count": count, "mkt": mkt, "safeSearch": safesearch}
    headers = {"Ocp-Apim-Subscription-Key": api_key}
    r = requests.get(url, headers=headers, params=params, timeout=12)
    r.raise_for_status()
    j = r.json()

    rows = []
    for it in j.get("webPages", {}).get("value", []):
        rows.append({
            "title": it.get("name",""),
            "link": it.get("url",""),
            "snippet": it.get("snippet",""),
            "source": it.get("displayUrl",""),
        })
        if len(rows) >= count: break
    return {"provider":"bing","q":q,"rows":rows,"matched":len(rows)}

# ====== 웹검색: Provider 3) Serper(구글 SERP 대행, 키 필요) ======
def search_serper(q: str, count: int = 10, gl: str = "kr", hl: str = "ko"):
    """
    https://serper.dev (Google 결과 대행)
    요구: SERPER_API_KEY
    """
    load_dotenv(".env")
    api_key = os.getenv("SERPER_API_KEY","").strip()
    if not api_key:
        raise RuntimeError("SERPER_API_KEY not set")

    url = "https://google.serper.dev/search"
    headers = {"X-API-KEY": api_key, "Content-Type":"application/json"}
    payload = {"q": q, "gl": gl, "hl": hl, "num": min(count, 20)}
    r = requests.post(url, headers=headers, data=json.dumps(payload), timeout=12)
    r.raise_for_status()
    j = r.json()

    rows = []
    for it in j.get("organic", []):
        rows.append({
            "title": it.get("title",""),
            "link": it.get("link",""),
            "snippet": it.get("snippet",""),
            "source": it.get("source",""),
        })
        if len(rows) >= count: break
    return {"provider":"serper","q":q,"rows":rows,"matched":len(rows)}

# ====== 웹검색: Provider 4) DuckDuckGo HTML (무키 폴백; 간단 파싱) ======
def search_ddg_html(q: str, count: int = 10):
    """
    https://html.duckduckgo.com/html/ 결과를 간단 파싱
    - API 키 불필요 / 결과 품질·안정성은 API 대비 떨어질 수 있음
    - 서비스 약관/robots.txt를 준수하여 책임 있는 사용 권장
    """
    url = "https://html.duckduckgo.com/html/"
    data = {"q": q}
    headers = {"User-Agent":"Mozilla/5.0"}
    r = requests.post(url, data=data, headers=headers, timeout=12)
    r.raise_for_status()

    rows = []
    if _HAS_BS4:
        soup = BeautifulSoup(r.text, "html.parser")
        for res in soup.select(".result__body"):
            a = res.select_one(".result__title a")
            if not a: continue
            title = a.get_text(strip=True)
            link  = a.get("href","")
            snippet_el = res.select_one(".result__snippet")
            snippet = snippet_el.get_text(" ", strip=True) if snippet_el else ""
            source_el = res.select_one(".result__url__domain")
            source = source_el.get_text(strip=True) if source_el else ""
            rows.append({"title":title,"link":link,"snippet":snippet,"source":source})
            if len(rows) >= count: break
    else:
        # 최소 파싱(BeautifulSoup 미설치 시)
        for m in re.finditer(r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', r.text, flags=re.S):
            link = m.group(1)
            title = strip_tags(m.group(2)).strip()
            rows.append({"title":title,"link":link,"snippet":"", "source":""})
            if len(rows) >= count: break

    return {"provider":"duckduckgo_html","q":q,"rows":rows,"matched":len(rows)}

# ====== 웹검색 통합 진입점 ======
def web_search(q: str, provider: str = "auto", count: int = 10, **opts):
    # 절대 provider 자체를 덮어쓰지 말고 새 이름 사용
    provider_norm = (provider or "auto").lower()

    def _try(fn):
        try:
            return fn()
        except Exception:
            return None

    if provider_norm == "brave":
        return search_brave(q, count=count, safesearch=opts.get("safesearch","moderate"))
    if provider_norm == "bing":
        return search_bing(q, count=count, mkt=opts.get("mkt","ko-KR"), safesearch=opts.get("safesearch","Moderate"))
    if provider_norm == "serper":
        return search_serper(q, count=count, gl=opts.get("gl","kr"), hl=opts.get("hl","ko"))
    if provider_norm == "ddg":
        return search_ddg_html(q, count=count)

    # auto fallback chain
    r = _try(lambda: search_brave(q, count=count, safesearch=opts.get("safesearch","moderate")))
    if r: return r
    r = _try(lambda: search_bing(q, count=count, mkt=opts.get("mkt","ko-KR"), safesearch=opts.get("safesearch","Moderate")))
    if r: return r
    r = _try(lambda: search_serper(q, count=count, gl=opts.get("gl","kr"), hl=opts.get("hl","ko")))
    if r: return r
    return search_ddg_html(q, count=count)
    
# ====== 직원검색 이름만 추출 ======
def extract_person_names(text: str) -> list[str]:
    # 단성/복성 성씨
    SURNAMES_1 = {
        "김","이","박","최","정","강","조","윤","장","임","한","오","서","신","권","황","안","송","홍",
        "류","유","전","고","문","손","배","백","허","남","노","심","하","곽","성","차","주","우","구",
        "민","진","나","지","엄","채","원","천","방","현","함","변","염","여","추","도","소","석","선",
        "설","마","길","연","위","표","명","기","라","왕","금","반","옥","육","인","맹","제","모","피","형","양"
    }
    SURNAMES_2 = {"남궁","황보","제갈","선우","서문","독고","사공","동방","탁발","왕손","어금","향목"}
    
    TITLE = r"(?:님|씨|군|양|과장|차장|부장|팀장|원장|교수|박사|선생님|대표|사원|대리|실장|연구원|주임|계장)"
    SEP   = r"[ \u00B7\u2027\.\-]?"  # 공백/가운뎃점/중점/점/하이픈
    
    SURNAME_ALT = "|".join(sorted(list(SURNAMES_2|SURNAMES_1), key=len, reverse=True))
    
    # ⚠️ f-string 쓰면 {1}이 포맷으로 먹힘 → {{1}}로 써야 함
    NAME_REGEX = re.compile(
        rf"(?<![가-힣])"                                   # 좌측이 한글이면 제외
        rf"((?:{SURNAME_ALT}){SEP}[가-힣]{{1}}{SEP}[가-힣]{{1}})"  # 성 + 이름2자
        rf"(?:{TITLE})?"                                   # 직함 허용(비캡처)
        rf"(?![가-힣])"                                    # 우측이 한글이면 제외
    )
    
    ORG_KEYWORDS = ("대학교","대학","병원","의료원","센터","연구소","주식회사","유한회사","법인")

    norm = re.sub(r"\s+", " ", text.strip())
    results = []
    for m in NAME_REGEX.finditer(norm):
        raw = m.group(1)
        name = re.sub(r"[ \u00B7\u2027\.\-]", "", raw)  # 구분자 제거 → DB키 형태

        # 기관/조직어 포함시 제외
        if any(k in name for k in ORG_KEYWORDS):
            continue

        # 성/이름 분해 검증
        if name[:2] in SURNAMES_2:
            given = name[2:]
        else:
            if name[0] not in SURNAMES_1:
                continue
            given = name[1:]

        if len(given) != 2:  # 이름은 2글자만
            continue

        if name not in results:
            results.append(name)
    return results

def excel_rows():
    try:
        df = pd.read_excel(EXCEL_PATH)   # ← 여기서 “요청 시” 읽음(지연 로딩)
        emp = df.loc[:7000].to_dict(orient="records")
        #return jsonify({"rows": len(df)})
        print(f"emp, {len(emp)}")
        return emp
    except FileNotFoundError:
        return jsonify({"error": f"Excel not found: {EXCEL_PATH}"}), 404


@app.get("/health")
def health():
    return {"status":"ok"}

@app.post("/")
def mcp():
    body = request.get_json(force=True)
    method = body.get("method")
    params = body.get("params", {}) or {}
    _id = body.get("id")

    # 0) 메서드 목록 (디스커버리)
    if method == "list_methods":
        return ok({
            "methods": [
                "list_methods",
                "list_resources",
                "read_resource",
                "query_resource",
                "web_search",
                "call_tool",
            ]
        }, _id)

    # 1) 리소스 목록
    if method == "list_resources":
        return ok({"resources":[
            {"name": "demo.emp", "description": "humc employee list"},
            {"name": "demo.patients", "description": "sample patients"},
        ]}, _id)

    # 2) 리소스 읽기
    if method == "read_resource":
        name = params.get("name")
        if name == "demo.emp":
            fields = params.get("fields")
            rows = emp
            if fields:
                rows = [{k:v for k,v in r.items() if k in fields} for r in rows]
            return ok({"rows": rows, "source":"demo"}, _id)

        if name == "demo.patients":
            return ok({"rows": PATIENTS, "source":"demo"}, _id)

        return err(404, f"unknown resource: {name}", _id)

    # 3) 리소스 쿼리(간단 필터)
    # params: {name: "demo.emp", q: "김", fields: ["성명","부서"] }
    if method == "query_resource":
        name = params.get("name")
        q = str(params.get("q","")).strip()
        fields = params.get("fields")  # None이면 모든 컬럼 검색

        if name not in ("demo.emp","demo.patients"):
            return err(404, f"unknown resource: {name}", _id)
            
        emp = excel_rows()
        
        rows = emp if name=="demo.emp" else PATIENTS
        if not q:
            return ok({"rows": rows, "matched": len(rows)}, _id)

        q_lower = q.lower()
        q_lower = extract_person_names(q_lower)[0]
        out = []
        for r in rows:
            keys = (fields or r.keys())
            hit = False
            for k in keys:
                v = r.get(k)
                if v is None: 
                    continue
                if q_lower in str(v).lower():
                    hit = True
                    break
            if hit:
                out.append(r)
        return ok({"rows": out, "matched": len(out)}, _id)

    ## 4) 웹 검색 메소뜨
    if method == "web_search":
        q = str(params.get("q","")).strip()
        if not q:
            return err(400, "web_search requires 'q'", _id)
    
        prov  = (params.get("provider") or "auto")   # ← 기본값 즉시 부여
        count = int(params.get("count", 10))
        opts  = {k: params[k] for k in ("safesearch","mkt","gl","hl") if k in params}
        try:
            data = web_search(q, provider=prov, count=count, **opts)
            return ok(data, _id)
        except requests.HTTPError as e:
            return err(502, "search upstream error", _id, data=str(e.response.text))
        except Exception as e:
            return err(500, f"web_search failed: {e}", _id)

    # 4) 툴 실행(액션/프록시)
    # params: {name: "emp.search", args:{q:"김", fields:["성명"]}}
    #      or {name: "hai.chat",  args:{messages:[...], model:"...", temperature:0.1}}
    if method == "call_tool":
        tool = params.get("name")
        args = params.get("args", {}) or {}

        # 4-1) 직원 검색 툴(리소스 쿼리 래핑)
        if tool == "emp.search":
            q = str(args.get("q","")).strip()
            fields = args.get("fields")  # e.g., ["성명","부서"]
            # 내부적으로 query_resource 호출과 동일 로직
            fake_req = {"method":"query_resource","params":{"name":"demo.emp","q":q,"fields":fields},"id":_id}
            with app.test_request_context(json=fake_req):
                return mcp()  # 재사용

        # 4-2) HAI 채팅 프록시(실제 LLM 호출)
        if tool == "hai.chat":
            messages = args.get("messages")
            if not messages:
                return err(400, "hai.chat requires 'messages'", _id)
            model = args.get("model")
            client_to_use = args.get("client_to_use","konanllm")
            # 선택 파라미터 전달(없으면 무시)
            extra = {k: args[k] for k in ("temperature","top_p","max_tokens","frequency_penalty","repetition_penalty") if k in args}
            try:
                content = call_hai_chat(messages, model=model, client_to_use=client_to_use, **extra)
                return ok({"message": content}, _id)
            except requests.HTTPError as e:
                return err(502, "HAI upstream error", _id, data=str(e.response.text))
            except Exception as e:
                return err(500, f"hai.chat failed: {e}", _id)
         
        # ====== (mcp() 내부: call_tool 분기에 툴 추가) ======
        if tool == "web.search":
            q = str(args.get("q","")).strip()
            if not q:
                return err(400, "web.search requires 'q'", _id)
        
            # ⚠️ provider_tool 같은 임시변수 쓰지 말고 바로 기본값 포함해서 받기
            prov  = (args.get("provider") or "auto")
            count = int(args.get("count", 10))
            opts  = {k: args[k] for k in ("safesearch","mkt","gl","hl") if k in args}
            try:
                data = web_search(q, provider=prov, count=count, **opts)
                return ok(data, _id)
            except requests.HTTPError as e:
                return err(502, "search upstream error", _id, data=str(e.response.text))
            except Exception as e:
                return err(500, f"web.search failed: {e}", _id)

                
        return err(404, f"unknown tool: {tool}", _id)

    # 기본: 미지원 메서드
    return err(-32601, "Method not found", _id)

if __name__ == "__main__":
    # 디버그 시 자동 리로더 끄려면 debug=False
    app.run(host="0.0.0.0", port=8080, debug=True)
