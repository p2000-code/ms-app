import os
import time
import logging
import requests
import concurrent.futures
import streamlit as st
import gc
import base64
import streamlit.components.v1 as components # ייבוא חדש לכפתור המיוחד
from bs4 import BeautifulSoup
from pypdf import PdfWriter
from weasyprint import HTML

# הגדרות תצוגה של Streamlit
st.set_page_config(page_title="הורדת ספרי חב\"ד", page_icon="📚", layout="centered")

# השתקת הודעות מערכת מיותרות
logging.getLogger('fontTools').setLevel(logging.WARNING)
logging.getLogger('weasyprint').setLevel(logging.WARNING)

# --- פונקציות עזר ---
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
        if line.startswith("מס' כרטיס"):
            continue
        metadata["תיאור"].append(line)
        
    return metadata

def create_cover_page_html(metadata, output_filename, range_text=""):
    desc_html = "".join([f"<p>{line}</p>" for line in metadata['תיאור']])
    
    # תוספת טקסט אם נבחר טווח עמודים
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

# הפונקציה החדשה לפתיחה בכרטיסייה חדשה
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

# --- ממשק המשתמש של Streamlit ---
st.title("📚 הורדת כתבי יד - ספריית חב\"ד")
st.markdown("הכנס את מספר כתב היד, והמערכת תייצר עבורך קובץ PDF מסודר להורדה וצפייה.")

ms_id_input = st.text_input("הכנס מספר כתב יד (למשל: 1102):")

# בחירת טווח עמודים
specific_range = st.checkbox("הורדת טווח עמודים ספציפי (במקום הספר השלם)")
start_page_input, end_page_input = 1, 10 

if specific_range:
    col1, col2 = st.columns(2)
    with col1:
        start_page_input = st.number_input("עמוד התחלה", min_value=1, value=1, step=1)
    with col2:
        end_page_input = st.number_input("עמוד סיום", min_value=1, value=10, step=1)

start_button = st.button("הכן ספר להורדה", type="primary")

# --- תהליך ההורדה ---
if start_button and ms_id_input:
    ms_id = ms_id_input.strip()
    
    if specific_range and start_page_input > end_page_input:
        st.error("שגיאה: עמוד ההתחלה לא יכול להיות גדול מעמוד הסיום.")
        st.stop()
        
    with st.spinner('אוסף נתונים ובונה דף שער...'):
        start_time = time.time() 
        metadata = get_manuscript_metadata(ms_id)
        
        range_text = f"חלק ספציפי: עמודים {start_page_input} עד {end_page_input}" if specific_range else ""
        cover_pdf = f"cover_page_{ms_id}.pdf"
        create_cover_page_html(metadata, cover_pdf, range_text)
        
        base_url = f"https://s3.wasabisys.com/chabadlibrary/ms/{ms_id}/{ms_id}_page_"
        
        chunk_files = [cover_pdf] 
        
        current_page = start_page_input if specific_range else 1
        target_end_page = end_page_input if specific_range else float('inf')
        
        keep_downloading = True
        download_batch_size = 25 
        
    status_text = st.empty()
    progress_bar = st.progress(0)
    
    while keep_downloading and current_page <= target_end_page:
        batch_end = min(current_page + download_batch_size - 1, target_end_page)
        
        status_text.info(f"מוריד ומעבד עמודים {current_page} עד {int(batch_end)}...")
        results = []
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=download_batch_size) as executor:
            futures = {executor.submit(download_single_page, p, base_url): p for p in range(current_page, int(batch_end) + 1)}
            for future in concurrent.futures.as_completed(futures):
                results.append(future.result())
        
        results.sort(key=lambda x: x[0]) 
        
        chunk_merger = PdfWriter()
        temp_single_pages = []
        
        for page_num, content, status in results:
            if content is None:
                if status == 404:
                    status_text.success(f"הגענו לסוף הספר (סה\"כ {page_num - 1} עמודים זמינים).")
                else:
                    st.error(f"⚠️ שגיאה בעמוד {page_num}: {status}")
                keep_downloading = False
                break 
            
            temp_pdf = f"temp_page_{page_num}_{ms_id}.pdf"
            with open(temp_pdf, 'wb') as f:
                f.write(content)
            
            chunk_merger.append(temp_pdf)
            temp_single_pages.append(temp_pdf)
        
        if temp_single_pages:
            chunk_filename = f"chunk_{current_page}_to_{current_page + len(temp_single_pages) - 1}_{ms_id}.pdf"
            chunk_merger.write(chunk_filename)
            chunk_files.append(chunk_filename)
        
        chunk_merger.close()
        
        for temp_pdf in temp_single_pages:
            if os.path.exists(temp_pdf): os.remove(temp_pdf)
            
        gc.collect() 
        
        current_page = int(batch_end) + 1
        
        if specific_range:
            total_pages_to_download = end_page_input - start_page_input + 1
            pages_done = current_page - start_page_input
            progress_bar.progress(min(pages_done / total_pages_to_download, 1.0))
        else:
            progress_bar.progress(min(current_page / 1000, 1.0)) 
        
        if keep_downloading and current_page <= target_end_page:
            time.sleep(1.5)

    status_text.info("מחבר את כל המקבצים לקובץ אחד, אנא המתן...")
    final_merger = PdfWriter()
    for chunk_file in chunk_files:
        final_merger.append(chunk_file)
        
    final_output = f"Manuscript_{ms_id}_Complete.pdf"
    final_merger.write(final_output)
    final_merger.close()
    
    for chunk_file in chunk_files:
        if os.path.exists(chunk_file): os.remove(chunk_file)
    gc.collect()
            
    total_time = round(time.time() - start_time, 2)
    progress_bar.empty()
    status_text.empty()
    st.success(f"✅ הספר {ms_id} מוכן! (זמן בנייה: {total_time} שניות)")
    
    st.write("---")
    
    # הצגת הכפתורים זה לצד זה
    col_dl, col_view = st.columns(2)
    
    with col_dl:
        # כפתור הורדה רגיל
        with open(final_output, "rb") as pdf_file:
            PDFbyte = pdf_file.read()
            
        st.download_button(
            label="📥 הורד קובץ למחשב",
            data=PDFbyte,
            file_name=final_output,
            mime='application/octet-stream',
            use_container_width=True
        )
        
    with col_view:
        # כפתור פתיחה בכרטיסייה חדשה
        open_pdf_in_new_tab(final_output, ms_id)

    # ניקוי מהשרת לאחר שהנתונים נטענו
    if os.path.exists(final_output): os.remove(final_output)
