from flask import Flask, request, jsonify, send_from_directory, session, redirect, Response
import os, traceback, json, re
from datetime import date

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "snapledger-dev-secret")

# ── Pages ─────────────────────────────────────────────────────────────────────

@app.route("/")
def home():
    return redirect("/app") if session.get("logged_in") else redirect("/login")

@app.route("/login")
def login_page():
    return send_from_directory(".", "login.html")

@app.route("/app")
def app_page():
    if not session.get("logged_in"):
        return redirect("/login")
    return send_from_directory(".", "app.html")

@app.route("/static/<path:filename>")
def static_files(filename):
    return send_from_directory("static", filename)

@app.route("/manifest.json")
def manifest():
    return send_from_directory("static", "manifest.json", mimetype="application/manifest+json")

@app.route("/sw.js")
def sw():
    return send_from_directory("static", "sw.js", mimetype="application/javascript")

# ── Auth ──────────────────────────────────────────────────────────────────────

@app.route("/api/auth/login", methods=["POST"])
def login():
    data = request.json or {}
    company_code = data.get("company_code", "").strip().upper()
    username     = data.get("username", "").strip()
    password     = data.get("password", "").strip()
    try:
        from db import get_supabase
        sb = get_supabase()
        r = sb.table("companies").select("*").eq("company_code", company_code).execute()
        if not r.data:
            return jsonify({"success": False, "error": "Company not found"}), 401
        c = r.data[0]
        if c["owner_username"] == username and c["owner_password"] == password:
            session["logged_in"]    = True
            session["company_code"] = company_code
            session["company_name"] = c["company_name"]
            session.permanent = True
            return jsonify({"success": True, "company_name": c["company_name"]})
        return jsonify({"success": False, "error": "Invalid credentials"}), 401
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

# ── Document scan ─────────────────────────────────────────────────────────────

@app.route("/api/documents/scan", methods=["POST"])
def scan_document():
    if not session.get("logged_in"):
        return jsonify({"error": "unauthorized"}), 401
    data       = request.json or {}
    image_data = data.get("image_data", "")
    if not image_data:
        return jsonify({"error": "image_data required"}), 400
    try:
        extracted = extract_with_claude(image_data)
        company_code = session["company_code"]
        items_mapped = apply_dictionary(extracted.get("items", []), company_code)

        from db import get_supabase
        sb = get_supabase()
        doc_r = sb.table("documents").insert({
            "company_code":   company_code,
            "doc_type":       extracted.get("doc_type", "other"),
            "supplier_name":  extracted.get("supplier_name"),
            "doc_date":       extracted.get("doc_date"),
            "doc_number":     extracted.get("doc_number"),
            "total_amount":   extracted.get("total_amount"),
            "currency":       extracted.get("currency", "UGX"),
            "notes":          extracted.get("notes", ""),
            "image_data":     image_data,
            "raw_extraction": json.dumps(extracted),
        }).execute()
        doc_id = doc_r.data[0]["id"] if doc_r.data else None

        if doc_id:
            for item in items_mapped:
                sb.table("doc_items").insert({
                    "document_id":          doc_id,
                    "company_code":         company_code,
                    "supplier_product_name":item.get("description", ""),
                    "our_product_name":     item.get("our_name") or item.get("description", ""),
                    "quantity":             item.get("quantity"),
                    "unit":                 item.get("unit"),
                    "unit_price":           item.get("unit_price"),
                    "total_price":          item.get("total_price"),
                    "needs_review":         item.get("needs_review", False),
                }).execute()

        review_count = sum(1 for i in items_mapped if i.get("needs_review"))
        return jsonify({
            "success":        True,
            "document_id":    doc_id,
            "extracted":      extracted,
            "items":          items_mapped,
            "review_needed":  review_count > 0,
            "review_count":   review_count,
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

def extract_with_claude(image_data):
    import anthropic
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        from config import ANTHROPIC_API_KEY
        api_key = ANTHROPIC_API_KEY
    client = anthropic.Anthropic(api_key=api_key)

    raw = image_data.split(",", 1)[1] if "," in image_data else image_data

    prompt = """Analyze this business document image and extract all data.

Return ONLY valid JSON — no explanation, no markdown:
{
  "doc_type": "invoice or receipt or delivery_note or proforma or credit_note or other",
  "supplier_name": "supplier name or null",
  "doc_date": "YYYY-MM-DD or null",
  "doc_number": "invoice/receipt number or null",
  "currency": "UGX or USD or KES — default UGX",
  "subtotal": number or null,
  "tax": number or null,
  "total_amount": number or null,
  "items": [
    {
      "description": "product name EXACTLY as written — do not change it",
      "quantity": number or null,
      "unit": "pcs or boxes or cartons or kg or null",
      "unit_price": number or null,
      "total_price": number or null
    }
  ],
  "notes": "any other info or empty string"
}

Rules: extract names exactly as written. Remove commas from numbers (1,500 → 1500). Include ALL line items."""

    msg = client.messages.create(
        model=os.environ.get("MODEL_NAME", "claude-sonnet-4-6"),
        max_tokens=2000,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": raw}},
            {"type": "text",  "text": prompt},
        ]}]
    )
    text  = msg.content[0].text.strip()
    match = re.search(r'\{.*\}', text, re.DOTALL)
    return json.loads(match.group() if match else text)

def apply_dictionary(items, company_code):
    try:
        from db import get_supabase
        sb = get_supabase()
        dict_r  = sb.table("product_dictionary").select("*").eq("company_code", company_code).execute()
        lookup  = {(e.get("supplier_product_name") or "").lower().strip(): e for e in (dict_r.data or [])}
    except Exception:
        lookup = {}

    result = []
    for item in items:
        desc     = (item.get("description") or "").strip()
        entry    = lookup.get(desc.lower())
        copy     = dict(item)
        copy["our_name"]     = entry["our_product_name"] if entry else None
        copy["dict_id"]      = entry["id"]               if entry else None
        copy["needs_review"] = entry is None
        result.append(copy)
    return result

# ── Documents list & detail ───────────────────────────────────────────────────

@app.route("/api/documents", methods=["GET"])
def list_documents():
    if not session.get("logged_in"):
        return jsonify({"error": "unauthorized"}), 401
    q     = request.args.get("q", "").strip()
    limit = int(request.args.get("limit", 50))
    try:
        from db import get_supabase
        sb = get_supabase()
        cc = session["company_code"]
        qb = sb.table("documents").select(
            "id,doc_type,supplier_name,doc_date,doc_number,total_amount,currency,created_at"
        ).eq("company_code", cc).order("created_at", desc=True).limit(limit)
        if q:
            qb = qb.ilike("supplier_name", f"%{q}%")
        return jsonify(qb.execute().data or [])
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/documents/<doc_id>", methods=["GET"])
def get_document(doc_id):
    if not session.get("logged_in"):
        return jsonify({"error": "unauthorized"}), 401
    try:
        from db import get_supabase
        sb  = get_supabase()
        doc = sb.table("documents").select("*").eq("id", doc_id).execute().data
        if not doc:
            return jsonify({"error": "not found"}), 404
        items = sb.table("doc_items").select("*").eq("document_id", doc_id).execute().data or []
        result         = doc[0]
        result["items"] = items
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/documents/<doc_id>", methods=["DELETE"])
def delete_document(doc_id):
    if not session.get("logged_in"):
        return jsonify({"error": "unauthorized"}), 401
    try:
        from db import get_supabase
        sb = get_supabase()
        sb.table("doc_items").delete().eq("document_id", doc_id).execute()
        sb.table("documents").delete().eq("id", doc_id).eq("company_code", session["company_code"]).execute()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── Review queue ──────────────────────────────────────────────────────────────

@app.route("/api/review", methods=["GET"])
def review_queue():
    if not session.get("logged_in"):
        return jsonify({"error": "unauthorized"}), 401
    try:
        from db import get_supabase
        sb = get_supabase()
        r  = sb.table("doc_items").select(
            "id,supplier_product_name,our_product_name,quantity,unit,unit_price,total_price,document_id,documents(supplier_name,doc_date,doc_type)"
        ).eq("company_code", session["company_code"]).eq("needs_review", True).order("created_at", desc=True).limit(100).execute()
        return jsonify(r.data or [])
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/review/<item_id>/confirm", methods=["POST"])
def confirm_item(item_id):
    if not session.get("logged_in"):
        return jsonify({"error": "unauthorized"}), 401
    our_name = (request.json or {}).get("our_product_name", "").strip()
    if not our_name:
        return jsonify({"error": "our_product_name required"}), 400
    try:
        from db import get_supabase
        sb   = get_supabase()
        cc   = session["company_code"]
        item = sb.table("doc_items").select("*").eq("id", item_id).execute().data
        if not item:
            return jsonify({"error": "not found"}), 404
        item = item[0]
        supplier_name = item.get("supplier_product_name", "")

        # Update this item
        sb.table("doc_items").update({"our_product_name": our_name, "needs_review": False}).eq("id", item_id).execute()

        # Save to dictionary
        existing = sb.table("product_dictionary").select("id").eq("company_code", cc).ilike("supplier_product_name", supplier_name).execute()
        if existing.data:
            sb.table("product_dictionary").update({"our_product_name": our_name, "confirmed": True}).eq("id", existing.data[0]["id"]).execute()
        else:
            sb.table("product_dictionary").insert({
                "company_code":          cc,
                "supplier_product_name": supplier_name,
                "our_product_name":      our_name,
                "confirmed":             True,
            }).execute()

        # Auto-apply to all other unreviewed items with same supplier name
        sb.table("doc_items").update({"our_product_name": our_name, "needs_review": False}).eq("company_code", cc).eq("supplier_product_name", supplier_name).eq("needs_review", True).execute()

        return jsonify({"success": True, "applied_to_all": True})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

# ── Product dictionary ────────────────────────────────────────────────────────

@app.route("/api/dictionary", methods=["GET"])
def list_dictionary():
    if not session.get("logged_in"):
        return jsonify({"error": "unauthorized"}), 401
    try:
        from db import get_supabase
        sb = get_supabase()
        r  = sb.table("product_dictionary").select("*").eq("company_code", session["company_code"]).order("our_product_name").execute()
        return jsonify(r.data or [])
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/dictionary/<did>", methods=["DELETE"])
def delete_dict_entry(did):
    if not session.get("logged_in"):
        return jsonify({"error": "unauthorized"}), 401
    try:
        from db import get_supabase
        sb = get_supabase()
        sb.table("product_dictionary").delete().eq("id", did).eq("company_code", session["company_code"]).execute()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── Stats ─────────────────────────────────────────────────────────────────────

@app.route("/api/stats", methods=["GET"])
def get_stats():
    if not session.get("logged_in"):
        return jsonify({"error": "unauthorized"}), 401
    try:
        from db import get_supabase
        sb    = get_supabase()
        cc    = session["company_code"]
        today = date.today().isoformat()
        month = date.today().replace(day=1).isoformat()
        docs  = sb.table("documents").select("id,doc_type,total_amount,created_at").eq("company_code", cc).execute().data or []
        pending = sb.table("doc_items").select("id").eq("company_code", cc).eq("needs_review", True).execute().data or []
        today_docs  = [d for d in docs if (d.get("created_at") or "")[:10] == today]
        month_docs  = [d for d in docs if (d.get("created_at") or "")[:10] >= month]
        month_spend = sum(float(d.get("total_amount") or 0) for d in month_docs)
        return jsonify({
            "total_documents": len(docs),
            "today_scanned":   len(today_docs),
            "month_scanned":   len(month_docs),
            "month_spend":     month_spend,
            "review_pending":  len(pending),
            "company_name":    session.get("company_name", ""),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── AI Q&A ────────────────────────────────────────────────────────────────────

@app.route("/api/ask", methods=["POST"])
def ask():
    if not session.get("logged_in"):
        return jsonify({"error": "unauthorized"}), 401
    question = (request.json or {}).get("question", "").strip()
    if not question:
        return jsonify({"error": "question required"}), 400
    try:
        import anthropic
        from db import get_supabase
        sb = get_supabase()
        cc = session["company_code"]
        docs  = sb.table("documents").select("id,doc_type,supplier_name,doc_date,doc_number,total_amount,currency,created_at").eq("company_code", cc).order("created_at", desc=True).limit(200).execute().data or []
        items = sb.table("doc_items").select("document_id,supplier_product_name,our_product_name,quantity,unit,unit_price,total_price").eq("company_code", cc).limit(500).execute().data or []

        system = f"""You are a smart business assistant for a wholesale shop. The user has {len(docs)} scanned documents in their system.

DOCUMENTS (most recent first):
{json.dumps(docs[:80], indent=2)}

LINE ITEMS:
{json.dumps(items[:200], indent=2)}

Answer questions clearly using this data. Be specific with numbers. Format currency with commas.
If the user asks to see/find/show a document, include SHOW_DOCUMENT:[the document uuid] in your response."""

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            from config import ANTHROPIC_API_KEY
            api_key = ANTHROPIC_API_KEY
        client  = anthropic.Anthropic(api_key=api_key)
        msg     = client.messages.create(
            model=os.environ.get("MODEL_NAME", "claude-sonnet-4-6"),
            max_tokens=1000,
            system=system,
            messages=[{"role": "user", "content": question}]
        )
        answer   = msg.content[0].text
        match    = re.search(r'SHOW_DOCUMENT:([a-f0-9\-]{36})', answer)
        show_id  = match.group(1) if match else None
        clean    = re.sub(r'SHOW_DOCUMENT:[a-f0-9\-]+', '', answer).strip()
        return jsonify({"answer": clean, "show_document_id": show_id})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

# ── CSV export ────────────────────────────────────────────────────────────────

@app.route("/api/export/items.csv")
def export_csv():
    if not session.get("logged_in"):
        return redirect("/login")
    try:
        import csv, io
        from db import get_supabase
        sb    = get_supabase()
        cc    = session["company_code"]
        docs  = {d["id"]: d for d in sb.table("documents").select("*").eq("company_code", cc).execute().data or []}
        items = sb.table("doc_items").select("*").eq("company_code", cc).execute().data or []
        out   = io.StringIO()
        w     = csv.writer(out)
        w.writerow(["Date","Supplier","Doc Type","Doc No","Supplier Product Name","Our Product Name","Qty","Unit","Unit Price","Total Price","Currency","Needs Review"])
        for i in items:
            d = docs.get(i.get("document_id"), {})
            w.writerow([
                (d.get("doc_date") or d.get("created_at",""))[:10],
                d.get("supplier_name",""),
                d.get("doc_type",""),
                d.get("doc_number",""),
                i.get("supplier_product_name",""),
                i.get("our_product_name",""),
                i.get("quantity",""),
                i.get("unit",""),
                i.get("unit_price",""),
                i.get("total_price",""),
                d.get("currency","UGX"),
                "Yes" if i.get("needs_review") else "No",
            ])
        return Response(out.getvalue(), mimetype="text/csv",
            headers={"Content-Disposition": f"attachment;filename=snapledger_{cc}_{date.today()}.csv"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── Company provisioning ──────────────────────────────────────────────────────

@app.route("/api/companies", methods=["POST"])
def create_company():
    if request.headers.get("X-Master-Key") != os.environ.get("MASTER_KEY", ""):
        return jsonify({"error": "unauthorized"}), 401
    data = request.json or {}
    try:
        from db import get_supabase
        sb = get_supabase()
        sb.table("companies").insert({
            "company_code":   data["company_code"].upper(),
            "company_name":   data["company_name"],
            "owner_username": data["owner_username"],
            "owner_password": data["owner_password"],
        }).execute()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
