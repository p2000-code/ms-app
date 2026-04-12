import os
import time
import logging
import requests
import concurrent.futures
import streamlit as st
import gc
import base64
import pandas as pd
import streamlit.components.v1 as components
from bs4 import BeautifulSoup
from pypdf import PdfWriter
from weasyprint import HTML

# הגדרות תצוגה של Streamlit
st.set_page_config(page_title="הורדת ספרי חב\"ד", page_icon="📚", layout="centered")

# השתקת הודעות מערכת מיותרות
logging.getLogger('fontTools').setLevel(logging.WARNING)
logging.getLogger('weasyprint').setLevel(logging.WARNING)

# --- פונקציות עזר ---

@st.cache_data
def load_catalog():
    file_name = 'catalog.csv'
    if os.path.exists(file_name):
        try:
            # קורא רק את העמודות הרלוונטיות (A=0, B=1, C=2, R=17)
            df = pd.read_csv(file_name, usecols=[0, 1, 2, 17], header=None, skiprows=1, encoding='utf-8')
            df.columns = ['ms_id', 'shelf', 'desc', 'pages']
            # ניקוי נתונים
            df['ms_id'] = df['ms_id'].astype(str).str.strip()
            return df
        except Exception as e:
            st.error(f"⚠️ שגיאה בקריאת קובץ הקטלוג: {e}")
            return None
    return None

df_catalog = load_catalog()

def get_manuscript_metadata(ms_id):
    url = f"https://chabadlibrary.org/catalog/index1.php?frame=main&catalog=mscatalog&mode=details&volno={ms_id}&limit=0&search_mode=simple"
    headers = {'User-Agent': 'Mozilla/5.0'}
    response = requests.get(url, headers=headers)
    response.encoding = 'utf-8'
    soup = BeautifulSoup(response.text, 'html.parser')
    
    lines = soup.get_text(separator='\n', strip=True).split('\n')
    metadata = {"מספר כתב יד": str(ms_id), "מדור ומדף": "", "תיאור": []}
    
    for line in lines:
        line = line.strip()
        if not line or "קטלוג ספריית" in line or "לתצלום הספר" in line or "chabadlibrary.org" in line:
            continue
        if "מדור ומדף:" in line:
            metadata["מדור ומדף"] = line.split("מדור ומדף:")[1].strip()
            continue
        metadata["תיאור"].append(line)
        
    return metadata

def create_cover_page_html(metadata, output_filename, range_text=""):
    desc_html = "".join([f"<p>{line}</p>" for line in metadata['תיאור']])
    range_html = f"<h3 style='color: #555;'>{range_text}</h3>" if range_text else ""
    
    html_content = f"""
    <!DOCTYPE html>
    <html dir="rtl" lang="he">
    <head>
        <meta charset="utf-8">
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Frank+Ruhl+Libre:wght@400;700&display=swap');
            body {{ font-family: 'Frank Ruhl Libre', serif; text-align: center; padding-top: 100px; color: #000; }}
            h1 {{ font-size: 50px; margin-bottom: 20px; }}
            h2 {{ font-size: 30px; margin-bottom: 20px; font-weight: normal; }}
            h3 {{ font-size: 24px; margin-bottom: 50px; font-weight: normal; }}
            .description {{ font-size: 24px; line-height: 1.8; }}
            p {{ margin: 8px 0; }}
        </style>
    </head>
    <body>
        <h1>כתב יד מספר {metadata['מספר כתב יד']}</h1>
        <h2>מדור ומדף: {metadata['מדור ומדף']}</h2>
        {range_html}
        <div class="description">{desc_html}</div>
    </body>
    </html>
    """
    HTML(string=html_content).write_pdf(output_filename)

def download_single_page(page_num, base_url, max_retries=3):
    url = f"{base_url}{page_num}.pdf"
    for attempt in range(max_retries):
        try:
            response = requests.get(url, timeout=15)
            if response.status_code == 200:
                return page_num, response.content, 200
            elif response.status_code == 404:
                return page_num, None, 404
            else:
                if attempt < max_retries - 1:
                    time.sleep(2)
                    continue
                return page_num, None, response.status_code
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2)
                continue
            return page_num, None, str(e)

def open_pdf_in_new_tab(file_path, ms_id):
    with open(file_path, "rb") as f:
        base64_pdf = base64.b64encode(f.read()).decode('utf-8')
    
    html_code = f"""
    <button onclick="
        var win = window.open('', '_blank');
        if(win) {{
            win.document.write('<title>כתב יד {ms_id}</title><iframe src=\\'data:application/pdf;base64,{base64_pdf}\\' frameborder=\\'0\\' style=\\'border:0; top:0px; left:0px; bottom:0px; right:0px; width:100%; height:100%; position:absolute;\\'></iframe>');
        }} else {{
            alert('נא לאפשר חלונות קופצים (Pop-ups) עבור אתר זה כדי לפתוח את הקובץ.');
        }}
    " style="cursor: pointer; padding: 10px 20px; color: white; background-color: #2b2b36; border: 1px solid #4a4a5a; border-radius: 5px; font-size: 16px; font-weight: bold; font-family: sans-serif; width: 100%; box-shadow: 0px 2px 5px rgba(0,0,0,0.2);">
        👁️ פתח קובץ בחלונית חדשה
    </button>
    """
    components.html(html_code, height=60)

# --- ממשק המשתמש ---
st.title("📚 הורדת כתבי יד - ספריית חב\"ד")

ms_id_input = st.text_input("הכנס מספר כתב יד (למשל: 1102):")

# חיפוש והצגה מהקטלוג
if ms_id_input and df_catalog is not None:
    ms_id_clean = ms_id_input.strip()
    row = df_catalog[df_catalog['ms_id'] == ms_id_clean]
    
    if not row.empty:
        ms_desc = row['desc'].values[0]
        ms_shelf = row['shelf'].values[0]
        ms_pages = row['pages'].values[0]
        
        st.info(f"📍 **מדור ומדף:** {ms_shelf}  \n📄 **תיאור:** {ms_desc}  \n🔢 **מספר דפים:** {ms_pages}")
        
        # בדיקה אם כתב היד ריק
        try:
            p_val = int(float(ms_pages))
            if p_val == 0:
                st.error("⚠️ כתב יד זה מסומן כריק במערכת. לא ניתן להוריד.")
                st.stop()
        except:
            pass
    else:
        st.warning("מספר כתב היד לא נמצא בקטלוג המקומי, אך ניתן לנסות להוריד.")

specific_range = st.checkbox("הורדת טווח עמודים ספציפי")
start_page_input, end_page_input = 1, 10 

if specific_range:
    col1, col2 = st.columns(2)
    with col1:
        start_page_input = st.number_input("עמוד התחלה", min_value=1, value=1, step=1)
    with col2:
        end_page_input = st.number_input("עמוד סיום", min_value=1, value=10, step=1)

start_button = st.button("הכן ספר להורדה", type="primary")

# --- תהליך ההורדה (נוסחה ישנה - כתיבה לדיסק) ---
if start_button and ms_id_input:
    ms_id = ms_id_input.strip()
    
    with st.spinner('מכין את הספר...'):
        start_time = time.time()
        metadata = get_manuscript_metadata(ms_id)
        
        range_text = f"עמודים {start_page_input} עד {end_page_input}" if specific_range else ""
        cover_pdf = f"cover_{ms_id}.pdf"
        create_cover_page_html(metadata, cover_pdf, range_text)
        
        base_url = f"https://s3.wasabisys.com/chabadlibrary/ms/{ms_id}/{ms_id}_page_"
        chunk_files = [cover_pdf]
        
        current_page = start_page_input if specific_range else 1
        target_end_page = end_page_input if specific_range else float('inf')
        keep_downloading = True
        
    status_text = st.empty()
    progress_bar = st.progress(0)
    
    while keep_downloading and current_page <= target_end_page:
        batch_size = 25
        batch_end = min(current_page + batch_size - 1, target_end_page)
        
        status_text.info(f"מוריד עמודים {current_page} עד {int(batch_end)}...")
        results = []
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=batch_size) as executor:
            futures = {executor.submit(download_single_page, p, base_url): p for p in range(current_page, int(batch_end) + 1)}
            for future in concurrent.futures.as_completed(futures):
                results.append(future.result())
        
        results.sort(key=lambda x: x[0])
        
        chunk_merger = PdfWriter()
        temp_files_to_delete = []
        
        for page_num, content, status in results:
            if content is None:
                if status == 404:
                    status_text.success("הגענו לסוף הספר.")
                keep_downloading = False
                break
            
            # כתיבה לדיסק (הנוסחה הישנה)
            temp_name = f"temp_{ms_id}_{page_num}.pdf"
            with open(temp_name, 'wb') as f:
                f.write(content)
            chunk_merger.append(temp_name)
            temp_files_to_delete.append(temp_name)
            
        if temp_files_to_delete:
            chunk_name = f"chunk_{ms_id}_{current_page}.pdf"
            chunk_merger.write(chunk_name)
            chunk_files.append(chunk_name)
            
        chunk_merger.close()
        for f in temp_files_to_delete:
            if os.path.exists(f): os.remove(f)
        
        current_page = int(batch_end) + 1
        progress_bar.progress(min(current_page / 500, 1.0)) # הערכה גסה לסרגל
        time.sleep(1)

    # איחוד סופי
    final_output = f"Manuscript_{ms_id}.pdf"
    final_merger = PdfWriter()
    for f in chunk_files:
        final_merger.append(f)
    final_merger.write(final_output)
    final_merger.close()
    
    for f in chunk_files:
        if os.path.exists(f): os.remove(f)
        
    st.success(f"✅ הספר מוכן!")
    
    col_dl, col_view = st.columns(2)
    with col_dl:
        with open(final_output, "rb") as f:
            st.download_button("📥 הורד קובץ", f, file_name=final_output)
    with col_view:
        open_pdf_in_new_tab(final_output, ms_id)
    
    if os.path.exists(final_output): os.remove(final_output)
