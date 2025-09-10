#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Chatbot de terminal para recomendar prendas con filtro inteligente + búsqueda semántica.
  - Primero filtra por metadata (marca, categoría, talles, colores, precio).
  - Luego usa embeddings PCA para rankear por similitud según la "intención" del usuario.
Uso:
  python chat_cli.py --artifacts ./artifacts --top_k 6
"""
import os, sys, argparse, re, math
import numpy as np
import pandas as pd
from dotenv import load_dotenv
from openai import OpenAI
from sklearn.metrics.pairwise import cosine_similarity
import joblib

def ensure_list(x):
    if x is None or (isinstance(x, float) and math.isnan(x)): return []
    if isinstance(x, list): return x
    if isinstance(x, str):
        parts = re.split(r"[|,/;]+|\s*,\s*", x)
        return [p.strip() for p in parts if p.strip()]
    return [str(x)]

def ask(prompt, default=None):
    s = input(prompt).strip()
    if not s and default is not None:
        return default
    return s

def yesno(prompt, default="n"):
    s = input(prompt + (" [s/N] " if default.lower().startswith("n") else " [S/n] ")).strip().lower()
    if not s:
        return default.lower().startswith("s")
    return s.startswith("s")

def build_intent_text(answers: dict) -> str:
    # resume en lenguaje natural para el embedding de consulta
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

def main():
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts", default="./artifacts", help="Carpeta donde están catalog.parquet, products_pca.parquet, pca.pkl")
    parser.add_argument("--top_k", type=int, default=6, help="Cantidad de productos a retornar")
    args = parser.parse_args()

    # Carga data + PCA
    cat_path = os.path.join(args.artifacts, "catalog.parquet")
    pca_path = os.path.join(args.artifacts, "pca.pkl")
    red_path = os.path.join(args.artifacts, "products_pca.parquet")
    if not (os.path.exists(cat_path) and os.path.exists(pca_path) and os.path.exists(red_path)):
        print("Faltan artefactos. Ejecutá primero: python preprocess.py --glob './data/*.csv' --outdir './artifacts'")
        sys.exit(1)

    catalog = pd.read_parquet(cat_path)
    df = pd.read_parquet(red_path)
    pca = joblib.load(pca_path)

    # Mapa de columnas embedding
    emb_cols = [c for c in df.columns if c.startswith("emb_")]
    emb_matrix = df[emb_cols].values.astype(np.float32)

    # Interacción
    print("🧠 Zoppa Stylist — Te voy a hacer algunas preguntas para recomendarte mejor.\n")

    answers = {}
    answers["occasion"] = ask("¿Para qué ocasión? (ej: casamiento, casual, oficina, noche, deporte): ")
    answers["category"] = ask("¿Qué tipo de prenda buscás? (ej: campera, remera, jean, vestido) o ENTER si no importa: ")
    answers["style"] = ask("¿Qué estilo preferís? (minimalista, urbano, elegante, deportivo, clásico) o ENTER: ")
    answers["fit"] = ask("¿Preferís fit oversize, regular o entallado? (ENTER si no importa): ")
    answers["brand_pref"] = ask("¿Alguna marca preferida? (separadas por coma) o ENTER: ").lower()
    answers["brand_avoid"] = ask("¿Alguna marca que NO querés? (coma) o ENTER: ").lower()
    answers["sizes"] = ask("¿Tus talles (ej: S, M, L, 42 de pantalón)? o ENTER: ")
    answers["colors_pref"] = ask("¿Colores preferidos? (coma) o ENTER: ").lower()
    answers["colors_avoid"] = ask("¿Colores a evitar? (coma) o ENTER: ").lower()
    budget = ask("¿Presupuesto aprox? podés poner 'min-max' (ej 30000-80000) o solo un máximo (ej 60000): ")
    answers["notes"] = ask("Notas extra (ej: llevar con zapatillas blancas, clima frío, lluvia, etc.) o ENTER: ")

    # Construir filtros de metadata
    df_f = df.copy()

    # Filtro por marca
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

    # Filtro por categoría
    if answers["category"]:
        catkey = answers["category"].strip().lower()
        df_f = df_f[df_f["category"].str.lower().str.contains(re.escape(catkey))]

    # Filtro por talles (si el usuario indica algo)
    if answers["sizes"]:
        wanted_sizes = [s.strip().lower() for s in re.split(r"[|,/;]+|\s*,\s*", answers["sizes"]) if s.strip()]
        def has_any_size(slist):
            sl = [s.lower() for s in slist] if isinstance(slist, list) else []
            return any(w in sl for w in wanted_sizes)
        df_f = df_f[df_f["sizes"].apply(has_any_size)]

    # Filtro por colores
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

    # Filtro por presupuesto
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

    # Si el filtro quedó vacío o muy chico, relajamos progresivamente
    if len(df_f) == 0:
        df_f = df.copy()  # sin filtro
    elif len(df_f) < 10 and answers.get("brand_pref"):
        # quita filtro de marca si muy restrictivo
        df_f = df.copy()
        if answers["category"]:
            catkey = answers["category"].strip().lower()
            df_f = df_f[df_f["category"].str.lower().str.contains(re.escape(catkey))]

    # Construye texto de intención y saca embedding
    intent = build_intent_text(answers)
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("Falta OPENAI_API_KEY en el entorno o .env")
        sys.exit(1)
    client = OpenAI(api_key=api_key)
    model = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")
    emb = client.embeddings.create(model=model, input=intent).data[0].embedding
    emb = np.array(emb, dtype=np.float32).reshape(1, -1)

    # Reduce con el mismo PCA
    reduced = pca.transform(emb)  # (1, k)

    # Matriz del subset
    sub = df_f.copy()
    sub_mat = sub[[c for c in sub.columns if c.startswith("emb_")]].values.astype(np.float32)

    # Similitud coseno
    sims = cosine_similarity(sub_mat, reduced).flatten()
    sub = sub.copy()
    sub["similarity"] = sims

    # Orden y top-k
    top = sub.sort_values("similarity", ascending=False).head(args.top_k)

    # Mostrar resultados
    print("\n🎯 Recomendaciones top por match semántico + filtros:")
    for i, row in enumerate(top.itertuples(index=False), start=1):
        price = "N/D" if (not hasattr(row, "price") or pd.isna(row.price)) else f"${int(row.price):,}".replace(",", ".")
        colors = ", ".join(row.colors) if isinstance(row.colors, list) and row.colors else "N/D"
        sizes  = ", ".join(row.sizes)  if isinstance(row.sizes, list)  and row.sizes  else "N/D"
        print(f"\n{i}. {row.name} — {row.brand}")
        print(f"   Categoría: {row.category}")
        print(f"   Precio: {price}")
        print(f"   Colores: {colors}")
        print(f"   Talles: {sizes}")
        print(f"   Score: {row.similarity:.4f}")
        # Imagen principal (si existe)
        img = None
        if isinstance(row.images, str) and row.images:
            # WooCommerce suele tener múltiples URLs separadas por coma
            img = row.images.split(',')[0].strip()
        if img:
            print(f"   Imagen: {img}")
        # descripción breve
        desc = (row.description or "") if hasattr(row, "description") else ""
        if len(desc) > 180: desc = desc[:180] + "…"
        if desc:
            print(f"   Descripción: {desc}")

    print("\n💡 Tip: corré de nuevo cambiando filtros (marca/categoría/talles/colores) para ajustar aún más.")
    print("    Tu intención buscada fue:", intent)

if __name__ == "__main__":
    main()
