import sys
import shutil

shutil.copy('utils/code33_engine.py', 'scratch/temp_engine.py')

with open('scratch/temp_engine.py', 'r', encoding='utf-8') as f:
    content = f.read()

search_str = """            seen.add(curr['end'])
            rate = (curr['val'] - prior['val']) / abs(prior['val']) * 100"""

replace_str = """            seen.add(curr['end'])
            rate = (curr['val'] - prior['val']) / abs(prior['val']) * 100
            print(f"YOY_PAIR: curr_end: {curr['end']:<10} | curr_val: {curr['val']:>6.3f} | prior_end: {prior['end']:<10} | prior_val: {prior['val']:>6.3f} | calculated_rate: {rate:+.1f}%")"""

content = content.replace(search_str, replace_str)

with open('scratch/temp_engine.py', 'w', encoding='utf-8') as f:
    f.write(content)
