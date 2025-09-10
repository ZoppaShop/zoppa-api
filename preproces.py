#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Preprocesa el catálogo de Zoppa (CSV/XLSX de WooCommerce), genera embeddings y PCA reducidos.
Uso:
  1) Crear y activar venv, instalar requerimientos (ver README del mensaje).
  2) Colocar tus archivos en ./data/ (puede haber varios CSV/XLSX).
  3) python preprocess.py --glob "./data/*.csv" --outdir "./artifacts"
Salidas:
  - artifacts/catalog.parquet (metadatos limpios y normalizados)
  - artifacts/products_embeddings.parquet (embeddings crudos como listas)
  - artifacts/pca.pkl (modelo PCA)
  - artifacts/products_pca.parquet (embeddings reducidos emb_0..emb_{k-1})
"""
import os, re, glob, math, json, argparse
import numpy as np
import pandas as pd
from tqdm import tqdm
from dotenv import load_dotenv
from openai import OpenAI
from sklearn.decomposition import PCA
import joblib

def as_list(x):
    if x is None or (isinstance(x, float) and math.isnan(x)): return []
    if isinstance(x, str):
        # soporta "S, M, L" o "S | M | L"
        parts = re.split(r"[|,/;]+|\s*,\s*", x)
        return [p.strip() for p in parts if p.strip()]
    if isinstance(x, (list, tuple, set)):
        return list(x)
    return [str(x)]

def parse_price(x):
    try:
        if pd.isna(x): return np.nan
        s = str(x)
        s = re.sub(r"[^\d.,]", "", s)  # quita símbolos
        # normaliza a punto decimal
        if s.count(",") == 1 and s.count(".") == 0:
            s = s.replace(",", ".")
        s = s.replace(",", "")
        return float(s)
    except Exception:
        return np.nan

def normalize_catalog(df: pd.DataFrame) -> pd.DataFrame:
    # Mapeo de columnas WooCommerce -> estándar
    colmap = {
        "SKU": "sku",
        "Marcas": "brand",
        "Nombre": "name",
        "Precio normal": "price",
        "Imágenes": "images",
        "Categorías": "category",
        "Descripción": "description",
        "¿En stock?": "in_stock",
        "Ventas dirigidas": "upsells",
    }
    for k, v in list(colmap.items()):
        if k not in df.columns:
            # intenta variantes por nombre
            for c in df.columns:
                if c.lower().strip() == k.lower():
                    colmap[k] = c
                    break

    out = pd.DataFrame()
    for k, v in colmap.items():
        if v in df.columns:
            out[colmap[k]] = df[v]
        elif k in df.columns:
            out[colmap[k]] = df[k]
        else:
            out[colmap[k]] = np.nan

    # Atributos (busca hasta 6 atributos)
    for i in range(1, 7):
        name_col = f"Nombre del atributo {i}"
        val_col  = f"Valor(es) del atributo {i}"
        if name_col in df.columns and val_col in df.columns:
            name_series = df[name_col].fillna("").astype(str).str.lower()
            val_series  = df[val_col].fillna("").astype(str)
            if f"attr_{i}_name" not in out: out[f"attr_{i}_name"] = name_series
            if f"attr_{i}_vals" not in out: out[f"attr_{i}_vals"] = val_series

    # Deriva 'sizes' y 'colors'
    sizes, colors = [], []
    for idx, _ in out.iterrows():
        row_sizes = []
        row_colors = []
        for i in range(1, 7):
            ncol = f"attr_{i}_name"
            vcol = f"attr_{i}_vals"
            if ncol in out.columns and vcol in out.columns:
                n = str(out.at[idx, ncol]).lower()
                v = str(out.at[idx, vcol])
                if "talle" in n or "tamaño" in n or "size" in n:
                    row_sizes.extend(as_list(v))
                if "color" in n:
                    row_colors.extend(as_list(v))
        sizes.append(sorted(list(dict.fromkeys([s.strip() for s in row_sizes if s.strip()]))))
        colors.append(sorted(list(dict.fromkeys([c.strip() for c in row_colors if c.strip()]))))
    out["sizes"] = sizes
    out["colors"] = colors

    # Limpieza
    out["price"] = out["price"].apply(parse_price)
    out["brand"] = out["brand"].fillna("").astype(str).str.strip()
    out["category"] = out["category"].fillna("").astype(str)
    out["name"] = out["name"].fillna("").astype(str)
    out["description"] = out["description"].fillna("").astype(str)
    out["images"] = out["images"].fillna("").astype(str)

    # Texto rico para embedding
    def build_text(row):
        blocks = [
            f"Nombre: {row['name']}",
            f"Marca: {row['brand']}",
            f"Categoría: {row['category']}",
            f"Descripción: {row['description']}",
            f"Talles: {', '.join(row['sizes']) if row['sizes'] else 'N/D'}",
            f"Colores: {', '.join(row['colors']) if row['colors'] else 'N/D'}",
            f"Precio: {row['price'] if not pd.isna(row['price']) else 'N/D'}",
        ]
        return " | ".join(blocks)

    out["embed_text"] = out.apply(build_text, axis=1)

    # Deduplicación razonable
    out = out.drop_duplicates(subset=["sku", "name", "brand", "category"], keep="first").reset_index(drop=True)
    return out

def batched(iterable, n=128):
    batch = []
    for x in iterable:
        batch.append(x)
        if len(batch) >= n:
            yield batch
            batch = []
    if batch:
        yield batch

def generate_embeddings(df: pd.DataFrame, client: OpenAI, model: str) -> np.ndarray:
    texts = df["embed_text"].astype(str).tolist()
    vectors = []
    total = math.ceil(len(texts)/128)
    for chunk in tqdm(batched(texts, n=128), total=total, desc="Embeddings"):
        resp = client.embeddings.create(model=model, input=chunk)
        for d in resp.data:
            vectors.append(d.embedding)
    return np.array(vectors, dtype=np.float32)

def main():
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("--glob", default="./data/*.*", help="Patrón de archivos CSV/XLSX de WooCommerce")
    parser.add_argument("--outdir", default="./artifacts", help="Carpeta de salida")
    args = parser.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    files = sorted(glob.glob(args.glob))
    if not files:
        raise SystemExit(f"No se encontraron archivos con patrón: {args.glob}")

    # Carga y normaliza
    dfs = []
    for fp in files:
        try:
            if fp.lower().endswith(".csv"):
                df = pd.read_csv(fp)
            elif fp.lower().endswith((".xlsx", ".xls")):
                df = pd.read_excel(fp)
            else:
                print(f"Saltando {fp} (extensión desconocida)")
                continue
            df_norm = normalize_catalog(df)
            dfs.append(df_norm)
            print(f"OK: {fp} -> {df_norm.shape[0]} filas")
        except Exception as e:
            print(f"ERROR leyendo {fp}: {e}")

    if not dfs:
        raise SystemExit("No se pudo cargar ningún archivo válido.")
    catalog = pd.concat(dfs, ignore_index=True).reset_index(drop=True)

    # Guarda catálogo limpio
    cat_path = os.path.join(args.outdir, "catalog.parquet")
    catalog.to_parquet(cat_path, index=False)
    print(f"✔ Guardado catálogo limpio: {cat_path} ({catalog.shape})")

    # Embeddings
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit("Falta OPENAI_API_KEY en el entorno o .env")
    client = OpenAI(api_key=api_key)
    model = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")

    vecs = generate_embeddings(catalog, client, model=model)
    dim = vecs.shape[1]
    emb_df = pd.DataFrame({"emb": vecs.tolist()})
    emb_path = os.path.join(args.outdir, "products_embeddings.parquet")
    emb_df.to_parquet(emb_path, index=False)
    print(f"✔ Guardado embeddings crudos: {emb_path} (dim={dim})")

    # PCA
    target_dim = int(os.environ.get("PCA_DIM", "256"))
    target_dim = min(target_dim, dim)
    pca = PCA(n_components=target_dim, random_state=42)
    reduced = pca.fit_transform(vecs)
    joblib.dump(pca, os.path.join(args.outdir, "pca.pkl"))
    print(f"✔ PCA entrenado a k={target_dim} y guardado en pca.pkl")

    # Guarda emb reducidos + metadatos
    red_cols = [f"emb_{i}" for i in range(reduced.shape[1])]
    reduced_df = pd.DataFrame(reduced, columns=red_cols)
    out = pd.concat([catalog, reduced_df], axis=1)
    out_path = os.path.join(args.outdir, "products_pca.parquet")
    out.to_parquet(out_path, index=False)
    print(f"✔ Guardado embeddings reducidos: {out_path} ({out.shape})")

if __name__ == "__main__":
    main()
