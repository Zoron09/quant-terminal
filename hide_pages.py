import os

files_to_hide = [
    "pages/2_Financials.py",
    "pages/3_Growth_and_Margins.py",
    "pages/4_Valuation.py",
    "pages/5_Earnings.py",
    "pages/6_Analyst_Ratings.py",
    "pages/9_SEPA_Analysis.py",
    "pages/11_News_Sentiment.py",
    "pages/13_Market_Dashboard.py"
]

for file_path in files_to_hide:
    full_path = os.path.join(r"C:\Users\Meet Singh\quant-terminal", file_path)
    if os.path.exists(full_path):
        with open(full_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # Check if already added
        if any('st.stop()' in line for line in lines[:20]):
            continue
        
        new_lines = []
        in_page_config = False
        replaced = False
        
        # Find where to inject
        insert_idx = 0
        for i, line in enumerate(lines):
            if line.startswith('import '):
                insert_idx = i + 1
            if line.startswith('from '):
                insert_idx = i + 1
        
        # We will just insert our block right after imports. We also need to strip existing st.set_page_config
        filtered_lines = []
        i = 0
        while i < len(lines):
            if 'st.set_page_config' in lines[i]:
                in_page_config = True
                if ')' in lines[i]:
                    in_page_config = False
                i += 1
                continue
            
            if in_page_config:
                if ')' in lines[i]:
                    in_page_config = False
                i += 1
                continue
                
            filtered_lines.append(lines[i])
            i += 1
            
        # Re-find insert index in filtered lines
        insert_idx = 0
        for i, line in enumerate(filtered_lines):
            if line.startswith('import ') or line.startswith('from '):
                insert_idx = i + 1
                
        injection = "st.set_page_config(page_title=\"Quant Terminal\")\nst.stop()\n"
        
        filtered_lines.insert(insert_idx, injection)
        
        with open(full_path, 'w', encoding='utf-8') as f:
            f.writelines(filtered_lines)
        print(f"Updated {file_path}")
    else:
        print(f"File not found: {file_path}")
