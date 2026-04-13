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

# אתחול זיכרון המערכת (כדי שהכפתורים לא ייעלמו)
if 'pdf_ready' not in st.session_state:
    st.session_state.pdf_ready = False
    st.session_state.pdf_data = None
    st.session_state.ms_id = ""

# 1. הגדרות תצוגה
st.set_page_config(page_title="הורדת ספרי חב\"ד", page_icon="📚", layout="centered")

st.markdown("""
    <style>
        div[data-testid="InputInstructions"] > span:nth-child(1) {
            visibility: hidden;
        }
        div[data-testid="InputInstructions"] > span:nth-child(1)::before {
            content: "לחץ אנטר (Enter) כדי לטעון את פרטי כתב היד";
            visibility: visible;
            display: block;
            color: #666;
            font-size: 14px;
        }
        .stMarkdown, .stText, .stInfo, .stError {
            direction: rtl;
            text-align: right;
        }
    </style>
""", unsafe_allow_html=True)

logging.getLogger('fontTools').setLevel(logging.WARNING)
logging.getLogger('weasyprint').setLevel(logging.WARNING)

@st.cache_data
def load_catalog():
    file_name = 'catalog.csv'
    if os.path.exists(file_name):
        try:
            df = pd.read_csv(file_name, usecols=[0, 1, 2, 17], header=None, skiprows=1, encoding='utf-8')
            df.columns = ['ms_id', 'shelf', 'desc', 'pages']
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
    try:
        response = requests.get(url, headers=headers, timeout=10)
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
    except:
        return {"מספר כתב יד": str(ms_id), "מדור ומדף": "לא נמצא", "תיאור": ["לא ניתן היה לשלוף תיאור מלא מהאתר"]}

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
            .description {{ font-size: 22px; line-height: 1.6; max-width: 80%; margin: 0 auto; }}
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
            time.sleep(1)
        except:
            time.sleep(1)
    return page_num, None, 500

# --- ממשק המשתמש ---

st.title("📚 הורדת כתבי יד - ספריית חב\"ד")

ms_id_input = st.text_input(
    "הכנס מספר כתב יד:", 
    placeholder="למשל: 1102",
    help="הקש Enter לאחר הזנת המספר כדי לראות את פרטי הספר"
)

if ms_id_input and df_catalog is not None:
    ms_id_clean = ms_id_input.strip()
    row = df_catalog[df_catalog['ms_id'] == ms_id_clean]
    
    if not row.empty:
        ms_desc = row['desc'].values[0]
        ms_shelf = row['shelf'].values[0]
        ms_pages = row['pages'].values[0]
        st.info(f"📍 **מדור ומדף:** {ms_shelf}  \n📄 **תיאור:** {ms_desc}  \n🔢 **מספר דפים:** {ms_pages}")
        try:
            total_p = int(float(ms_pages))
            if total_p == 0:
                st.error("⚠️ כתב יד זה מוגדר כריק במערכת (0 דפים). לא ניתן להוריד.")
                st.stop()
        except:
            pass
    else:
        st.warning("מספר כתב היד לא נמצא בקטלוג המקומי, אך ניתן לנסות להוריד ישירות מהשרת.")

specific_range = st.checkbox("אני רוצה להוריד רק טווח עמודים ספציפי")
start_page, end_page = 1, 10
if specific_range:
    c1, c2 = st.columns(2)
    with c1: start_page = st.number_input("עמוד התחלה", min_value=1, value=1)
    with c2: end_page = st.number_input("עמוד סיום", min_value=1, value=10)

# תהליך ההורדה
if st.button("הכן ספר להורדה 📥", type="primary"):
    if not ms_id_input:
        st.warning("אנא הכנס מספר כתב יד.")
    else:
        ms_id = ms_id_input.strip()
        # איפוס נתונים קודמים אם היו
        st.session_state.pdf_ready = False 
        
        with st.spinner('בונה את דף השער ואוסף נתונים...'):
            meta = get_manuscript_metadata(ms_id)
            range_txt = f"עמודים {start_page} עד {end_page}" if specific_range else ""
            cover_file = f"cover_{ms_id}.pdf"
            create_cover_page_html(meta, cover_file, range_txt)
            
            base_url = f"https://s3.wasabisys.com/chabadlibrary/ms/{ms_id}/{ms_id}_page_"
            chunk_files = [cover_file]
            
            curr = start_page if specific_range else 1
            last = end_page if specific_range else 2000 
            keep_going = True
            
        status = st.empty()
        progress = st.progress(0)
        
        while keep_going and curr <= last:
            batch_size = 20
            limit = min(curr + batch_size - 1, last)
            status.info(f"מעבד עמודים {curr} עד {limit}...")
            
            results = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=batch_size) as executor:
                futures = {executor.submit(download_single_page, p, base_url): p for p in range(curr, limit + 1)}
                for f in concurrent.futures.as_completed(futures):
                    results.append(f.result())
            
            results.sort(key=lambda x: x[0])
            chunk_merger = PdfWriter()
            temp_list = []
            
            for p_num, content, code in results:
                if content is None:
                    if code == 404: status.success("הגענו לסוף הדפים הזמינים.")
                    keep_going = False
                    break
                
                temp_name = f"temp_{ms_id}_{p_num}.pdf"
                with open(temp_name, 'wb') as f:
                    f.write(content)
                chunk_merger.append(temp_name)
                temp_list.append(temp_name)
            
            if temp_list:
                chunk_name = f"chunk_{ms_id}_{curr}.pdf"
                chunk_merger.write(chunk_name)
                chunk_files.append(chunk_name)
            
            chunk_merger.close()
            for f in temp_list: 
                if os.path.exists(f): os.remove(f)
            
            curr = limit + 1
            progress.progress(min(curr / 500, 1.0))
            time.sleep(0.5)

        # איחוד סופי
        final_file = f"Manuscript_{ms_id}.pdf"
        final_merger = PdfWriter()
        for f in chunk_files:
            final_merger.append(f)
        final_merger.write(final_file)
        final_merger.close()
        
        # --- השינוי המרכזי מתחיל כאן ---
        # קריאת הקובץ המוכן ושמירתו בזיכרון של Streamlit
        with open(final_file, "rb") as f:
            st.session_state.pdf_data = f.read()
            st.session_state.pdf_ready = True
            st.session_state.ms_id = ms_id
        
        # ניקוי מהדיסק
        for f in chunk_files: 
            if os.path.exists(f): os.remove(f)
        if os.path.exists(final_file): os.remove(final_file)
        gc.collect()
        
        status.empty()
        progress.empty()
        st.rerun() # מרענן את העמוד כדי להציג את הכפתורים בצורה בטוחה

# --- תצוגת הכפתורים לאחר שהספר מוכן ---
if st.session_state.pdf_ready:
    st.success(f"✅ הספר {st.session_state.ms_id} מוכן!")
    st.divider()
    
    col1, col2 = st.columns(2)
    with col1:
        st.download_button(
            label="📥 הורד קובץ למחשב",
            data=st.session_state.pdf_data,
            file_name=f"Manuscript_{st.session_state.ms_id}.pdf",
            mime='application/pdf',
            use_container_width=True
        )
    with col2:
        # יצירת כפתור הצפייה מתוך הזיכרון
        base64_pdf = base64.b64encode(st.session_state.pdf_data).decode('utf-8')
        html_code = f"""
        <button onclick="
            var win = window.open('', '_blank');
            if(win) {{
                win.document.write('<title>כתב יד {st.session_state.ms_id}</title><iframe src=\\'data:application/pdf;base64,{base64_pdf}\\' frameborder=\\'0\\' style=\\'border:0; top:0px; left:0px; bottom:0px; right:0px; width:100%; height:100%; position:absolute;\\'></iframe>');
            }} else {{
                alert('נא לאפשר חלונות קופצים בדפדפן כדי לצפות בקובץ.');
            }}
        " style="cursor: pointer; padding: 10px 20px; color: white; background-color: #2b2b36; border: 1px solid #4a4a5a; border-radius: 5px; font-size: 16px; font-weight: bold; width: 100%; height: 45px;">
            👁️ צפה בכתב היד בחלונית חדשה
        </button>
        """
        components.html(html_code, height=60)
