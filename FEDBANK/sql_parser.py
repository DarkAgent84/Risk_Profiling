import re
import csv
import io
import time
import pandas as pd

def parse_sql_inserts(filepath):
    print(f"Parsing {filepath}...")
    t0 = time.time()
    
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        columns = None
        rows = []
        
        for line in f:
            line_str = line.strip()
            if not line_str:
                continue
            if line_str.startswith("INSERT INTO"):
                m = re.search(r'\((.*?)\)\s+VALUES', line_str)
                if m:
                    columns = [c.strip().strip('"') for c in m.group(1).split(',')]
                continue
            
            # Line is a tuple:  (val1, val2, ...), or (val1, val2, ...);
            if line_str.startswith('('):
                # strip trailing comma or semicolon
                val_content = line_str[1:]
                if val_content.endswith('),') or val_content.endswith(');'):
                    val_content = val_content[:-2]
                elif val_content.endswith(')'):
                    val_content = val_content[:-1]
                
                # Parse with csv reader
                # Replace NULL with a sentinel or None
                reader = csv.reader(io.StringIO(val_content), delimiter=',', quotechar="'", escapechar='\\')
                try:
                    for row in reader:
                        cleaned = [None if item.strip() == 'NULL' else item for item in row]
                        rows.append(cleaned)
                except Exception as e:
                    pass

    df = pd.DataFrame(rows, columns=columns)
    print(f"Parsed {len(df):,} rows x {len(columns)} cols in {time.time()-t0:.2f}s")
    return df

print("=== PARSING FEDBANK RAW SQL FILES ===")
df_soa = parse_sql_inserts('data/raw/soa_data_v3_nopii_202609081853 (1).sql')
df_mis = parse_sql_inserts('data/raw/collection_data_v3_nopii_202609081853 (1).sql')

# Save as CSVs so standard pipeline can also use them directly!
df_soa.to_csv('data/raw/Customer_Data.csv', index=False)
df_mis.to_csv('data/raw/Collection_Data.csv', index=False)
print("Saved Customer_Data.csv and Collection_Data.csv in data/raw/")
