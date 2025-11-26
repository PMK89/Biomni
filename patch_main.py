import sys
from pathlib import Path

path = Path("biomni_esqlabs_app/main.py")
content = path.read_text()

old_code = """    index_path = PROJECT_ROOT / "biomni_esqlabs_app" / "templates" / "index.html"
    with open(index_path, "r") as f:
        return HTMLResponse(content=f.read())"""

new_code = """    index_path = PROJECT_ROOT / "biomni_esqlabs_app" / "templates" / "index.html"
    with open(index_path, "r") as f:
        content = f.read()

    # Dynamically inject the correct root path for static assets
    root_path = request.scope.get("root_path", "").rstrip("/")
    if root_path:
        content = content.replace('href="static/', f'href="{root_path}/static/')
        content = content.replace('src="static/', f'src="{root_path}/static/')
        content = content.replace('href="/static/', f'href="{root_path}/static/')
        content = content.replace('src="/static/', f'src="{root_path}/static/')

    return HTMLResponse(content=content)"""

if old_code in content:
    new_content = content.replace(old_code, new_code)
    path.write_text(new_content)
    print("Successfully patched main.py")
else:
    print("Could not find target code block in main.py")
