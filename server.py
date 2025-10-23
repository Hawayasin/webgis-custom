import json
import os
from http.server import SimpleHTTPRequestHandler, HTTPServer
import subprocess

# Use db_config helpers (connection pool, env-driven config)
from db_config import get_conn, run_query, PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD, close_pool

UPLOAD_FOLDER = "static/uploads"

class WebGISHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/data.geojson":
            self.get_geojson()
        elif self.path == "/download":
            self.download_shapefile()
        else:
            super().do_GET()

    def do_POST(self):
        if self.path == "/upload":
            self.upload_shapefile()
        elif self.path == "/add_feature":
            self.add_feature()
        else:
            self.send_error(404, "Endpoint not found")

    # --- GET data dari PostGIS ---
    def get_geojson(self):
        sql = """
            SELECT jsonb_build_object(
                'type', 'FeatureCollection',
                'features', jsonb_agg(
                    jsonb_build_object(
                        'type', 'Feature',
                        'geometry', ST_AsGeoJSON(geom)::jsonb,
                        'properties', to_jsonb(row) - 'geom'
                    )
                )
            )
            FROM (SELECT * FROM feature) AS row;
        """
        row = run_query(sql, params=(), fetch='one')
        # run_query with fetch='one' returns a single row tuple; the JSON is at index 0
        geojson = row[0] if row else {"type": "FeatureCollection", "features": []}

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(geojson).encode())

    # --- Upload shapefile ke PostGIS ---
    def upload_shapefile(self):
        content_type = self.headers['Content-Type']
        if not content_type:
            self.send_error(400, "No Content-Type header")
            return
            
        boundary = content_type.split("=")[1].encode()
        remainbytes = int(self.headers['Content-Length'])
        line = self.rfile.readline()
        remainbytes -= len(line)
        
        if not boundary in line:
            self.send_error(400, "Content NOT begin with boundary")
            return
            
        line = self.rfile.readline()
        remainbytes -= len(line)
        
        fn = None
        if b'Content-Disposition' in line:
            fn = line.decode()
            if 'filename=' in fn:
                fn = fn.split('filename=')[1].strip().strip('"')
                
        if not fn:
            self.send_error(400, "Can't find out file name")
            return
            
        filepath = os.path.join(UPLOAD_FOLDER, os.path.basename(fn))
        line = self.rfile.readline()
        remainbytes -= len(line)
        line = self.rfile.readline()
        remainbytes -= len(line)
        
        try:
            with open(filepath, 'wb') as out:
                preline = self.rfile.readline()
                remainbytes -= len(preline)
                while remainbytes > 0:
                    line = self.rfile.readline()
                    remainbytes -= len(line)
                    if boundary in line:
                        preline = preline[0:-1]
                        if preline.endswith(b'\r'):
                            preline = preline[0:-1]
                        out.write(preline)
                        break
                    else:
                        out.write(preline)
                        preline = line
        except Exception as e:
            self.send_error(500, f"Error saving file: {str(e)}")
            return

        # Import to PostGIS using ogr2ogr and PG connection parameters from env
        pg_conn_str = f"PG:host={PGHOST} port={PGPORT} dbname={PGDATABASE} user={PGUSER} password={PGPASSWORD}"
        subprocess.run([
            "ogr2ogr", "-f", "PostgreSQL",
            pg_conn_str,
            filepath, "-nln", "feature", "-append"
        ])

        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Upload berhasil dan data tersimpan di PostGIS.")

    # --- Simpan hasil digitasi dari frontend ---
    def add_feature(self):
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        geojson = json.loads(post_data)

        geom = json.dumps(geojson['geometry'])
        name = geojson['properties'].get('name', 'Hasil Digitasi')
        # Use pooled connection
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO feature (name, geom)
                    VALUES (%s, ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326))
                """, (name, geom))
                conn.commit()

        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Fitur baru berhasil disimpan ke PostGIS.")

    # --- Download shapefile ---
    def download_shapefile(self):
        output_dir = "data/output_shp"
        os.makedirs(output_dir, exist_ok=True)
        pg_conn_str = f"PG:host={PGHOST} port={PGPORT} dbname={PGDATABASE} user={PGUSER} password={PGPASSWORD}"
        subprocess.run([
            "ogr2ogr", "-f", "ESRI Shapefile", f"{output_dir}/feature.shp",
            pg_conn_str,
            "feature"
        ])
        subprocess.run(["zip", "-r", "data/output_shp.zip", output_dir])

        with open("data/output_shp.zip", "rb") as f:
            data = f.read()

        self.send_response(200)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Disposition", "attachment; filename=bangunan.zip")
        self.end_headers()
        self.wfile.write(data)

# Jalankan server
server = HTTPServer(('localhost', 8000), WebGISHandler)
print("Server berjalan di http://localhost:8000")
server.serve_forever()
