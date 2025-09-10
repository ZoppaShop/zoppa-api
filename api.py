#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Web API version of the Zoppa Chatbot
"""
import os, sys, re, math
import numpy as np
import pandas as pd
from dotenv import load_dotenv
from openai import OpenAI
from sklearn.metrics.pairwise import cosine_similarity
import joblib
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # Allow cross-origin requests

# Load models and data
load_dotenv()
ARTIFACTS_DIR = os.environ.get("ARTIFACTS_DIR", "./artifacts")
TOP_K = int(os.environ.get("TOP_K", "6"))

# Functions from your original script
def ensure_list(x):
    # Same as your original function
    if x is None or (isinstance(x, float) and math.isnan(x)): return []
    if isinstance(x, list): return x
    if isinstance(x, str):
        parts = re.split(r"[|,/;]+|\s*,\s*", x)
        return [p.strip() for p in parts if p.strip()]
    return [str(x)]

def build_intent_text(answers: dict) -> str:
    # Same as your original function
    blocks = []
    if answers.get("occasion"): blocks.append(f"Ocasion: {answers['occasion']}")
    if answers.get("category"): blocks.append(f"Categoria buscada: {answers['category']}")
    if answers.get("style"): blocks.append(f"Estilo deseado: {answers['style']}")
    if answers.get("fit"): blocks.append(f"Fit: {answers['fit']}")
    if answers.get("brand_pref"): blocks.append(f"Prefiere marcas: {answers['brand_pref']}")
    if answers.get("brand_avoid"): blocks.append(f"Evitar marcas: {answers['brand_avoid']}")
    if answers.get("colors_pref"): blocks.append(f"Colores preferidos: {answers['colors_pref']}")
    if answers.get("colors_avoid"): blocks.append(f"Evitar colores: {answers['colors_avoid']}")
    if answers.get("sizes"): blocks.append(f"Talles: {answers['sizes']}")
    if answers.get("budget"): blocks.append(f"Presupuesto: {answers['budget']}")
    if answers.get("notes"): blocks.append(f"Notas: {answers['notes']}")
    return " | ".join(blocks)

# Load data at startup
try:
    cat_path = os.path.join(ARTIFACTS_DIR, "catalog.parquet")
    pca_path = os.path.join(ARTIFACTS_DIR, "pca.pkl")
    red_path = os.path.join(ARTIFACTS_DIR, "products_pca.parquet")
    
    catalog = pd.read_parquet(cat_path)
    df = pd.read_parquet(red_path)
    pca = joblib.load(pca_path)
    
    # Mapa de columnas embedding
    emb_cols = [c for c in df.columns if c.startswith("emb_")]
    emb_matrix = df[emb_cols].values.astype(np.float32)
    
    # Initialize OpenAI client
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("Missing OPENAI_API_KEY in environment")
    client = OpenAI(api_key=api_key)
    model = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")
    
    print("Data and models loaded successfully!")
except Exception as e:
    print(f"Error loading data: {e}")
    sys.exit(1)

@app.route('/api/recommend', methods=['POST'])
def recommend():
    # Get user input from POST request
    data = request.json
    answers = {
        "occasion": data.get("occasion", ""),
        "category": data.get("category", ""),
        "style": data.get("style", ""),
        "fit": data.get("fit", ""),
        "brand_pref": data.get("brand_pref", "").lower(),
        "brand_avoid": data.get("brand_avoid", "").lower(),
        "sizes": data.get("sizes", ""),
        "colors_pref": data.get("colors_pref", "").lower(),
        "colors_avoid": data.get("colors_avoid", "").lower(),
        "notes": data.get("notes", "")
    }
    budget = data.get("budget", "")
    
    # Apply the same filtering logic as in your CLI
    df_f = df.copy()

    # Filter by brand
    if answers["brand_pref"]:
        prefs = [b.strip() for b in answers["brand_pref"].split(",") if b.strip()]
        mask = False
        for p in prefs:
            mask = mask | df_f["brand"].str.lower().str.contains(re.escape(p))
        df_f = df_f[mask]
    if answers["brand_avoid"]:
        avoids = [b.strip() for b in answers["brand_avoid"].split(",") if b.strip()]
        for a in avoids:
            df_f = df_f[~df_f["brand"].str.lower().str.contains(re.escape(a))]

    # Filter by category
    if answers["category"]:
        catkey = answers["category"].strip().lower()
        df_f = df_f[df_f["category"].str.lower().str.contains(re.escape(catkey))]

    # Filter by sizes
    if answers["sizes"]:
        wanted_sizes = [s.strip().lower() for s in re.split(r"[|,/;]+|\s*,\s*", answers["sizes"]) if s.strip()]
        def has_any_size(slist):
            sl = [s.lower() for s in slist] if isinstance(slist, list) else []
            return any(w in sl for w in wanted_sizes)
        df_f = df_f[df_f["sizes"].apply(has_any_size)]

    # Filter by colors
    if answers["colors_pref"]:
        wanted_colors = [c.strip().lower() for c in answers["colors_pref"].split(",") if c.strip()]
        def has_any_color(clist):
            cl = [c.lower() for c in clist] if isinstance(clist, list) else []
            return any(w in cl for w in wanted_colors)
        df_f = df_f[df_f["colors"].apply(has_any_color)]
    if answers["colors_avoid"]:
        avoid_colors = [c.strip().lower() for c in answers["colors_avoid"].split(",") if c.strip()]
        def avoid_any_color(clist):
            cl = [c.lower() for c in clist] if isinstance(clist, list) else []
            return not any(a in cl for a in avoid_colors)
        df_f = df_f[df_f["colors"].apply(avoid_any_color)]

    # Filter by budget
    if budget:
        lo, hi = None, None
        m1 = re.match(r"^\s*(\d+)\s*-\s*(\d+)\s*$", budget)
        m2 = re.match(r"^\s*(\d+)\s*$", budget)
        if m1:
            lo, hi = int(m1.group(1)), int(m1.group(2))
        elif m2:
            lo, hi = 0, int(m2.group(1))
        if lo is not None and hi is not None and "price" in df_f.columns:
            df_f = df_f[(df_f["price"] >= lo) & (df_f["price"] <= hi)]

    # Handle empty results
    if len(df_f) == 0:
        df_f = df.copy()
    elif len(df_f) < 10 and answers.get("brand_pref"):
        df_f = df.copy()
        if answers["category"]:
            catkey = answers["category"].strip().lower()
            df_f = df_f[df_f["category"].str.lower().str.contains(re.escape(catkey))]

    # Get embeddings and calculate similarity
    intent = build_intent_text(answers)
    emb = client.embeddings.create(model=model, input=intent).data[0].embedding
    emb = np.array(emb, dtype=np.float32).reshape(1, -1)
    
    # Reduce with PCA
    reduced = pca.transform(emb)
    
    # Calculate similarity
    sub = df_f.copy()
    sub_mat = sub[[c for c in sub.columns if c.startswith("emb_")]].values.astype(np.float32)
    sims = cosine_similarity(sub_mat, reduced).flatten()
    sub["similarity"] = sims
    
    # Get top results
    top = sub.sort_values("similarity", ascending=False).head(TOP_K)
    
    # Format results for JSON response
    results = []
    for i, row in enumerate(top.itertuples(index=False), start=1):
        price = None if (not hasattr(row, "price") or pd.isna(row.price)) else int(row.price)
        colors = row.colors if isinstance(row.colors, list) and row.colors else []
        sizes = row.sizes if isinstance(row.sizes, list) and row.sizes else []
        
        # Handle image URL
        img = None
        if isinstance(row.images, str) and row.images:
            img = row.images.split(',')[0].strip()
            
        # Description
        desc = (row.description or "") if hasattr(row, "description") else ""
        
        results.append({
            "id": i,
            "name": row.name,
            "brand": row.brand,
            "category": row.category,
            "price": price,
            "colors": colors,
            "sizes": sizes,
            "similarity": float(row.similarity),
            "image": img,
            "description": desc,
            "product_id": row.product_id if hasattr(row, "product_id") else None
        })
    
    return jsonify({
        "intent": intent,
        "results": results
    })

@app.route('/', methods=['GET'])
def index():
    """Provide basic API information at the root URL"""
    return jsonify({
        "name": "Zoppa Stylist API",
        "version": "1.0.0",
        "endpoints": {
            "/api/recommend": "POST - Get product recommendations based on user preferences"
        },
        "status": "running"
    })

# Optional: Add a health check endpoint
@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "healthy"})

if __name__ == "__main__":
    # Get port from environment variable or default to 8080
    port = int(os.environ.get("PORT", 8080))
    # Important: bind to 0.0.0.0 to allow external connections
    app.run(host="0.0.0.0", port=port)