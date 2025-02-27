import json
import gradio as gr
import urllib.request
import urllib.parse
import urllib.error
import os
import io
import re
import time
import errno
import requests
import hashlib
import base64
from PIL import Image
from pathlib import Path
from urllib.parse import urlparse
from modules.shared import cmd_opts, opts
from scripts.civitai_global import print
import scripts.civitai_global as gl
import scripts.civitai_api as _api
import scripts.civitai_file_manage as _file
import scripts.civitai_download as _download
from PIL import Image
from io import BytesIO

try:
    from send2trash import send2trash
except ImportError:
    print("Python module 'send2trash' has not been imported correctly, please try to restart or install it manually.")
try:
    from bs4 import BeautifulSoup
except ImportError:
    print("Python module 'BeautifulSoup' has not been imported correctly, please try to restart or install it manually.")

gl.init()

offlineHTML = '<div style="font-size: 24px; text-align: center; margin: 50px !important;">The Civit-API has timed out, please try again.<br>The servers might be too busy or the selected model could not be found.</div>'
css_path = Path(__file__).resolve().parents[1] / "style_html.css"
no_update = False
from_ver = False
from_tag = False
from_installed = False
try:
    queue = not cmd_opts.no_gradio_queue
except AttributeError:
    queue = not cmd_opts.disable_queue
except:
    queue = True

def delete_model(delete_finish=None, model_filename=None, model_string=None, list_versions=None, sha256=None, selected_list=None, model_ver=None, model_json=None):
    deleted = False
    model_id = None
    
    if model_string:
        _, model_id = _api.extract_model_info(model_string)
    
    if not model_ver:
        model_versions = _api.update_model_versions(model_id)
    else: model_versions = model_ver
    
    (model_name, ver_value, ver_choices) = _file.card_update(model_versions, model_string, list_versions, False)
    if not model_json:
        if model_id != None:
            selected_content_type = None
            for item in gl.json_data['items']:
                if int(item['id']) == int(model_id):
                    selected_content_type = item['type']
                    desc = item['description']
                    break
            
            if selected_content_type is None:
                print("Model ID not found in json_data. (delete_model)")
                return
    else:
        for item in model_json["items"]:
            selected_content_type = item['type']
            desc = item['description']
    
    model_folder = os.path.join(_api.contenttype_folder(selected_content_type, desc))
    
    # Delete based on provided SHA-256 hash
    if sha256:
        sha256_upper = sha256.upper()
        for root, _, files in os.walk(model_folder, followlinks=True):
            for file in files:
                if file.endswith('.json'):
                    file_path = os.path.join(root, file)
                    try:
                        with open(file_path, 'r', encoding="utf-8") as json_file:
                            data = json.load(json_file)
                            file_sha256 = data.get('sha256', '')
                            if file_sha256:
                                file_sha256 = file_sha256.upper()
                    except Exception as e:
                        print(f"Failed to open: {file_path}: {e}")
                        file_sha256 = "0"
                        
                    if file_sha256 == sha256_upper:
                        unpack_list = data.get('unpackList', [])
                        for unpacked_file in unpack_list:
                            unpacked_file_path = os.path.join(root, unpacked_file)
                            if os.path.isfile(unpacked_file_path):
                                try:
                                    send2trash(unpacked_file_path)
                                    print(f"File moved to trash based on unpackList: {unpacked_file_path}")
                                except:
                                    os.remove(unpacked_file_path)
                                    print(f"File deleted based on unpackList: {unpacked_file_path}")
                        
                        base_name, _ = os.path.splitext(file)
                        if os.path.isfile(file_path):
                            try:
                                send2trash(file_path)
                                print(f"Model moved to trash based on SHA-256: {file_path}")
                            except:
                                os.remove(file_path)
                                print(f"Model deleted based on SHA-256: {file_path}")
                            delete_associated_files(root, base_name)
                            deleted = True

    # Fallback to delete based on filename if not deleted based on SHA-256
    filename_to_delete = os.path.splitext(model_filename)[0]
    aria2_file = model_filename + ".aria2"
    if not deleted:
        for root, dirs, files in os.walk(model_folder, followlinks=True):
            for file in files:
                current_file_name = os.path.splitext(file)[0]
                if filename_to_delete == current_file_name or aria2_file == file:
                    path_file = os.path.join(root, file)
                    if os.path.isfile(path_file):
                        try:
                            send2trash(path_file)
                            print(f"Model moved to trash based on filename: {path_file}")
                        except:
                            os.remove(path_file)
                            print(f"Model deleted based on filename: {path_file}")
                        delete_associated_files(root, current_file_name)

    number = _download.random_number(delete_finish)


    btnDwn = not selected_list or selected_list == "[]"
    
    return (
            gr.Button.update(interactive=btnDwn, visible=btnDwn),  # Download Button
            gr.Button.update(interactive=False, visible=False),  # Cancel Button
            gr.Button.update(interactive=False, visible=False),  # Delete Button
            gr.Textbox.update(value=number),  # Delete Finish Trigger
            gr.Textbox.update(value=model_name),  # Current Model 
            gr.Dropdown.update(value=ver_value, choices=ver_choices)  # Version List
    )

def delete_associated_files(directory, base_name):
    for file in os.listdir(directory):
        current_base_name, ext = os.path.splitext(file)
        if current_base_name == base_name or current_base_name == f"{base_name}.preview" or current_base_name == f"{base_name}.api_info":
            path_to_delete = os.path.join(directory, file)
            try:
                send2trash(path_to_delete)
                print(f"Associated file moved to trash: {path_to_delete}")
            except:
                os.remove(path_to_delete)
                print(f"Associated file deleted: {path_to_delete}")

def save_preview(file_path, api_response, overwrite_toggle=False, sha256=None):
    json_file = os.path.splitext(file_path)[0] + ".json"
    install_path, file_name = os.path.split(file_path)
    name = os.path.splitext(file_name)[0]
    filename = f'{name}.preview.png'
    image_path = os.path.join(install_path, filename)
    
    if not overwrite_toggle:
        if os.path.exists(image_path):
            return
    
    if not sha256:
        if os.path.exists(json_file):
            try:
                with open(json_file, 'r', encoding="utf-8") as f:
                    data = json.load(f)
                    if 'sha256' in data and data['sha256']:
                        sha256 = data['sha256'].upper()
            except Exception as e:
                print(f"Failed to open {json_file}: {e}")
    else:
        sha256 = sha256.upper()

    for item in api_response["items"]:
        for version in item["modelVersions"]:
            for file_entry in version["files"]:
                if file_entry["hashes"].get("SHA256") == sha256:
                    for image in version["images"]:
                        if image["type"] == "image":
                            url_with_width = re.sub(r'/width=\d+', f'/width={image["width"]}', image["url"])

                            response = requests.get(url_with_width)
                            if response.status_code == 200:
                                image_file = BytesIO(response.content)
                                img = Image.open(image_file)
                                img.save(image_path)
                                print(f"Preview saved at \"{image_path}\"")
                            else:
                                print(f"Failed to save preview. Status code: {response.status_code}")

                            return
                    print(f"No preview images found for \"{name}\"")
                    return

def get_image_path(install_path, api_response, sub_folder):
    image_location = getattr(opts, "image_location", r"")
    sub_image_location = getattr(opts, "sub_image_location", True)
    image_path = install_path
    if api_response:
        json_info = api_response['items'][0]
    else:
        json_info = gl.json_info
    if image_location:
        if sub_image_location:
            desc = json_info['description']
            content_type = json_info['type']
            image_path = os.path.join(_api.contenttype_folder(content_type, desc, custom_folder=image_location))
            
            if sub_folder and sub_folder != "None" and sub_folder != "Only available if the selected files are of the same model type":
                image_path = os.path.join(image_path, sub_folder.lstrip("/").lstrip("\\"))
        else:
            image_path = Path(image_location)
    make_dir(image_path)
    return image_path

def save_images(preview_html, model_filename, install_path, sub_folder, api_response=None):
    image_path = get_image_path(install_path, api_response, sub_folder)
    img_urls = re.findall(r'data-sampleimg="true" src=[\'"]?([^\'" >]+)', preview_html)
    
    name = os.path.splitext(model_filename)[0]

    opener = urllib.request.build_opener()
    opener.addheaders = [('User-agent', 'Mozilla/5.0')]
    urllib.request.install_opener(opener)

    for i, img_url in enumerate(img_urls):
        filename = f'{name}_{i}.png'
        img_url = urllib.parse.quote(img_url, safe=':/=')
        try:
            with urllib.request.urlopen(img_url) as url:
                image_file = BytesIO(url.read())
                img = Image.open(image_file)
                img.save(os.path.join(install_path, filename))
                print(f"Downloaded {filename}")
                    
        except urllib.error.URLError as e:
            print(f'Error: {e.reason}')

def card_update(gr_components, model_name, list_versions, is_install):
    if gr_components:
        version_choices = gr_components['choices']
    else:
        print("Couldn't retrieve version, defaulting to installed")
        model_name += ".New"
        return model_name, None, None
    
    if is_install and not gl.download_fail and not gl.cancel_status:
        version_value_clean = list_versions + " [Installed]"
        version_choices_clean = [version if version + " [Installed]" != version_value_clean else version_value_clean for version in version_choices]
        
    else:
        version_value_clean = list_versions.replace(" [Installed]", "")
        version_choices_clean = [version if version.replace(" [Installed]", "") != version_value_clean else version_value_clean for version in version_choices]
    
    first_version_installed = "[Installed]" in version_choices_clean[0]
    any_later_version_installed = any("[Installed]" in version for version in version_choices_clean[1:])

    if first_version_installed:
        model_name += ".New"
    elif any_later_version_installed:
        model_name += ".Old"
    else:
        model_name += ".None"
    
    return model_name, version_value_clean, version_choices_clean

def list_files(folders):
    model_files = []
    
    extensions = ['.pt', '.ckpt', '.pth', '.safetensors', '.th', '.zip', '.vae']
    
    for folder in folders:
        if folder and os.path.exists(folder):
            for root, _, files in os.walk(folder, followlinks=True):
                for file in files:
                    _, file_extension = os.path.splitext(file)
                    if file_extension.lower() in extensions:
                        model_files.append(os.path.join(root, file))

    model_files = sorted(list(set(model_files)))
    return model_files

def gen_sha256(file_path):
    json_file = os.path.splitext(file_path)[0] + ".json"
    
    if os.path.exists(json_file):
        try:
            with open(json_file, 'r', encoding="utf-8") as f:
                data = json.load(f)
        
            if 'sha256' in data and data['sha256']:
                hash_value = data['sha256']
                return hash_value
        except Exception as e:
            print(f"Failed to open {json_file}: {e}")
        
    def read_chunks(file, size=io.DEFAULT_BUFFER_SIZE):
        while True:
            chunk = file.read(size)
            if not chunk:
                break
            yield chunk
    
    blocksize = 1 << 20
    h = hashlib.sha256()
    length = 0
    with open(os.path.realpath(file_path), 'rb') as f:
        for block in read_chunks(f, size=blocksize):
            length += len(block)
            h.update(block)

    hash_value = h.hexdigest()
    
    if os.path.exists(json_file):
        try:
            with open(json_file, 'r', encoding="utf-8") as f:
                data = json.load(f)
    
            if 'sha256' in data and data['sha256']:
                data['sha256'] = hash_value
                
            with open(json_file, 'w', encoding="utf-8") as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            print(f"Failed to open {json_file}: {e}")
    else:
        data = {'sha256': hash_value}
        with open(json_file, 'w', encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    
    return hash_value

def convert_local_images(html):
    soup = BeautifulSoup(html)
    for simg in soup.find_all("img", attrs={"data-sampleimg": "true"}):
        url = urlparse(simg["src"])
        path = url.path
        if not os.path.exists(path):
            print("URL path does not exist: %s" % url.path)
            # Try the raw url, files can be saved in windows as "C:\..." and
            # that confuses urlparse because people only really test on Linux.
            if os.path.exists(simg["src"]):
                path = simg["src"]
            else:
                continue
        with open(path, 'rb') as f:
            imgdata = f.read()
        b64img = base64.b64encode(imgdata).decode('utf-8')
        imgtype = Image.open(io.BytesIO(imgdata)).format
        if not imgtype:
            imgtype = "PNG"
        simg["src"] = f"data:image/{imgtype};base64,{b64img}"
    return str(soup)

def model_from_sent(model_name, content_type, tile_count):
    modelID_failed = False
    output_html = None
    model_file = None
    use_local_html = getattr(opts, "use_local_html", False)
    local_path_in_html = getattr(opts, "local_path_in_html", False)
    
    div = '<div style="color: white; font-family: var(--font); font-size: 24px; text-align: center; margin: 50px !important;">'
    not_found = div + "Model ID not found.<br>Maybe the model doesn\'t exist on CivitAI?</div>"
    path_not_found = div + "Model ID not found.<br>Could not locate the model path.</div>"
    offline = div + "CivitAI failed to respond.<br>The servers are likely offline."
        
    model_name = re.sub(r'\.\d{3}$', '', model_name)
    content_type = re.sub(r'\.\d{3}$', '', content_type)
    content_mapping = {
        "txt2img_textual_inversion_cards_html": ['TextualInversion'],
        "txt2img_hypernetworks_cards_html": ['Hypernetwork'],
        "txt2img_checkpoints_cards_html": ['Checkpoint'],
        "txt2img_lora_cards_html": ['LORA', 'LoCon']
    }
    content_type = content_mapping.get(content_type, content_type)
    
    extensions = ['.pt', '.ckpt', '.pth', '.safetensors', '.th', '.zip', '.vae']

    for content_type_item in content_type:
        folder = _api.contenttype_folder(content_type_item)
        for folder_path, _, files in os.walk(folder, followlinks=True):
            for file in files:
                if file.startswith(model_name) and file.endswith(tuple(extensions)):
                    model_file = os.path.join(folder_path, file)
                    
    if not model_file:
        output_html = path_not_found
        print(f'Error: Could not find model path for model: "{model_name}"')
        print(f'Content type: "{content_type}"')
        print(f'Main folder path: "{folder}"')
        use_local_html = False
        
    if use_local_html:
        html_file = os.path.splitext(model_file)[0] + ".html"
        if os.path.exists(html_file):
            with open(html_file, 'r', encoding='utf-8') as html:
                output_html = html.read()
                index = output_html.find("</head>")
                if index != -1:
                    output_html = output_html[index + len("</head>"):]
                if local_path_in_html:
                    output_html = convert_local_images(output_html)
    
    if not output_html:
        modelID = get_models(model_file, True)
        if not modelID or modelID == "Model not found":
            output_html = not_found
            modelID_failed = True
        if modelID == "offline":
            output_html = offline
            modelID_failed = True
        if not modelID_failed: 
            json_data = _api.api_to_data(content_type, "Newest", "AllTime", "Model name", None, None, None, tile_count, f"civitai.com/models/{modelID}")
        else:
            json_data = None
        
        if json_data == "timeout":
            output_html = offline
        if json_data != None and json_data != "timeout":
            model_versions = _api.update_model_versions(modelID, json_data)
            output_html = _api.update_model_info(None, model_versions.get('value'), True, modelID, json_data)
    
    css_path = Path(__file__).resolve().parents[1] / "style_html.css"
    with open(css_path, 'r', encoding='utf-8') as css_file:
        css = css_file.read()
    replacements = {
        '#0b0f19': 'var(--body-background-fill)',
        '#F3F4F6': 'var(--body-text-color)',
        'white': 'var(--body-text-color)',
        '#80a6c8': 'var(--secondary-300)',
        '#60A5FA': 'var(--link-text-color-hover)',
        '#1F2937': 'var(--input-background-fill)',
        '#374151': 'var(--input-border-color)',
        '#111827': 'var(--error-background-fill)',
        'top: 50%;': '',
        'padding-top: 0px;': 'padding-top: 475px;',
        '.civitai_txt2img': '.civitai_placeholder'
    }

    for old, new in replacements.items():
        css = css.replace(old, new)
    
    style_tag = f'<style>{css}</style>'
    head_section = f'<head>{style_tag}</head>'

    output_html = output_html.replace('display:flex;align-items:flex-start;', 'display:flex;align-items:flex-start;flex-wrap:wrap;justify-content:center;')
    output_html = str(head_section + output_html)
    output_html = output_html.replace('zoom-radio', 'zoom-preview-radio')   
    output_html = output_html.replace('zoomRadio', 'zoomPreviewRadio')
    output_html = output_html.replace('zoom-overlay', 'zoom-preview-overlay')
    output_html = output_html.replace('resetZoom', 'resetPreviewZoom')
    
    number = _download.random_number()
    
    return (
        gr.Textbox.update(value=output_html, placeholder=number), # Preview HTML
    )
    
def is_image_url(url):
    image_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.bmp']
    parsed = urlparse(url)
    path = parsed.path
    return any(path.endswith(ext) for ext in image_extensions)

def clean_description(desc):
    try:
        soup = BeautifulSoup(desc, 'html.parser')
        for a in soup.find_all('a', href=True):
            link_text = a.text + ' ' + a['href']
            if not is_image_url(a['href']):
                a.replace_with(link_text)

        cleaned_text = soup.get_text()
    except ImportError:
        print("Python module 'BeautifulSoup' was not imported correctly, cannot clean description. Please try to restart or install it manually.")
        cleaned_text = desc
    return cleaned_text

def make_dir(path):
    try:
        if not os.path.exists(path):
            os.makedirs(path)
    except OSError as e:
        if e.errno == errno.EACCES:
            try:
                os.makedirs(path, mode=0o777)
            except OSError as e:
                if e.errno == errno.EACCES:
                    print("Permission denied even with elevated permissions.")
                else:
                    print(f"Error creating directory: {e}")
        else:
            print(f"Error creating directory: {e}")
    except Exception as e:
        print(f"Error creating directory: {e}")

def save_model_info(install_path, file_name, sub_folder, sha256=None, preview_html=None, overwrite_toggle=False, api_response=None):
    filename = os.path.splitext(file_name)[0]
    json_file = os.path.join(install_path, f'{filename}.json')
    make_dir(install_path)
    
    save_api_info = getattr(opts, "save_api_info", False)
    use_local = getattr(opts, "local_path_in_html", False)
    save_to_custom = getattr(opts, "save_to_custom", False)
    
    if not api_response:
        api_response = gl.json_data
    
    image_path = get_image_path(install_path, api_response, sub_folder)
    
    if save_to_custom:
        save_path = image_path
    else:
        save_path = install_path
    
    result = find_and_save(api_response, sha256, file_name, json_file, False, overwrite_toggle)
    if result != "found":
        result = find_and_save(api_response, sha256, file_name, json_file, True, overwrite_toggle)            
    
    if preview_html:
        if use_local:
            img_urls = re.findall(r'data-sampleimg="true" src=[\'"]?([^\'" >]+)', preview_html)
            for i, img_url in enumerate(img_urls):
                img_name = f'{filename}_{i}.png'
                preview_html = preview_html.replace(img_url,f'{os.path.join(image_path, img_name)}')
                
        match = re.search(r'(\s*)<div class="model-block">', preview_html)
        if match:
            indentation = match.group(1)
        else:
            indentation = ''
        css_link = f'<link rel="stylesheet" type="text/css" href="{css_path}">'
        utf8_meta_tag = f'{indentation}<meta charset="UTF-8">'
        head_section = f'{indentation}<head>{indentation}    {utf8_meta_tag}{indentation}    {css_link}{indentation}</head>'
        HTML = head_section + preview_html
        path_to_new_file = os.path.join(save_path, f'{filename}.html')
        with open(path_to_new_file, 'wb') as f:
            f.write(HTML.encode('utf8'))
        
    if save_api_info:
        path_to_new_file = os.path.join(save_path, f'{filename}.api_info.json')
        with open(path_to_new_file, mode="w", encoding="utf-8") as f:
            json.dump(gl.json_info, f, indent=4, ensure_ascii=False)

    
def find_and_save(api_response, sha256=None, file_name=None, json_file=None, no_hash=None, overwrite_toggle=None):
    for item in api_response.get('items', []):
        for model_version in item.get('modelVersions', []):
            for file in model_version.get('files', []):
                file_name_api = file.get('name', '')
                sha256_api = file.get('hashes', {}).get('SHA256', '')
                
                if file_name == file_name_api if no_hash else sha256 == sha256_api:
                    gl.json_info = item
                    trained_words = model_version.get('trainedWords', [])
                    model_id = model_version.get('modelId', '')
                    
                    if model_id:
                        model_url = f'Model URL: \"https://civitai.com/models/{model_id}\"\n'
                    
                    description = item.get('description', '')
                    if description != None:
                        description = clean_description(description)
                        description = model_url + description
                    
                    base_model = model_version.get('baseModel', '')
                    
                    if base_model.startswith("SD 1"):
                        base_model = "SD1"
                    elif base_model.startswith("SD 2"):
                        base_model = "SD2"
                    elif base_model.startswith("SDXL"):
                        base_model = "SDXL"
                    else:
                        base_model = "Other"
                    
                    if isinstance(trained_words, list):
                        trained_tags = ",".join(trained_words)
                        trained_tags = re.sub(r'<[^>]*:[^>]*>', '', trained_tags)
                        trained_tags = re.sub(r', ?', ', ', trained_tags)
                        trained_tags = trained_tags.strip(', ')
                    else:
                        trained_tags = trained_words
                    
                    if os.path.exists(json_file):
                        with open(json_file, 'r', encoding="utf-8") as f:
                            try:
                                content = json.load(f)
                            except:
                                content = {}
                    else:
                        content = {}
                    changed = False
                    if not overwrite_toggle:
                        if "activation text" not in content or not content["activation text"]:
                            content["activation text"] = trained_tags
                            changed = True
                        if "description" not in content or not content["description"]:
                            content["description"] = description
                            changed = True
                        if "sd version" not in content or not content["sd version"]:
                            content["sd version"] = base_model
                            changed = True
                    else:
                        content["activation text"] = trained_tags
                        content["description"] = description
                        content["sd version"] = base_model
                        changed = True
                    
                    with open(json_file, 'w', encoding="utf-8") as f:
                        json.dump(content, f, indent=4)
                        
                    if changed: print(f"Model info saved to \"{json_file}\"")
                    return "found"
    
    return "not found"

def get_models(file_path, gen_hash=None):
    modelId = None
    sha256 = None
    json_file = os.path.splitext(file_path)[0] + ".json"
    if os.path.exists(json_file):
        try:
            with open(json_file, 'r', encoding="utf-8") as f:
                data = json.load(f)
                
                if 'modelId' in data:
                    modelId = data['modelId']
                if 'sha256' in data and data['sha256']:
                    sha256 = data['sha256']
        except Exception as e:
            print(f"Failed to open {json_file}: {e}")
    
    if not modelId or not sha256 or modelId == "Model not found":
        if gen_hash:
            if not sha256:
                sha256 = gen_sha256(file_path)
            by_hash = f"https://civitai.com/api/v1/model-versions/by-hash/{sha256}"
        else:
            if modelId:
                return modelId
            else:
                return None
    
    try:
        if not modelId or modelId == "Model not found":
            response = requests.get(by_hash, timeout=(10,30))
            if response.status_code == 200:
                api_response = response.json()
                if 'error' in api_response:
                    print(f"\"{file_path}\": {api_response['error']}")
                    return None
                else:
                    modelId = api_response.get("modelId", "")
            elif response.status_code == 503:
                return "offline"
            elif response.status_code == 404:
                api_response = response.json()
                modelId = api_response.get("error", "")
            
            if os.path.exists(json_file):
                try:
                    with open(json_file, 'r', encoding="utf-8") as f:
                        data = json.load(f)

                    data['modelId'] = modelId
                    data['sha256'] = sha256.upper()
                        
                    with open(json_file, 'w', encoding="utf-8") as f:
                        json.dump(data, f, indent=4)
                except Exception as e:
                    print(f"Failed to open {json_file}: {e}")
            else:
                data = {
                    'modelId': modelId,
                    'sha256': sha256.upper()
                    }
                with open(json_file, 'w', encoding="utf-8") as f:
                    json.dump(data, f, indent=4)
        
        return modelId
    except requests.exceptions.Timeout:
        print(f"Request timed out for {file_path}. Skipping...")
        return "offline"
    except requests.exceptions.ConnectionError:
        print("Failed to connect to the API. The CivitAI servers might be offline.")
        return "offline"
    except Exception as e:
        print(f"An error occurred for {file_path}: {str(e)}")
        return None

def version_match(file_paths, api_response):
    updated_models = []
    outdated_models = []
    sha256_hashes = {}
    for file_path in file_paths:
        json_path = f"{os.path.splitext(file_path)[0]}.json"
        if os.path.exists(json_path):
            with open(json_path, 'r', encoding="utf-8") as f:
                try:
                    json_data = json.load(f)
                    sha256 = json_data.get('sha256')
                    if sha256:
                        sha256_hashes[os.path.basename(file_path)] = sha256.upper()
                except Exception as e:
                    print(f"Failed to open {json_path}: {e}")
        
    file_names_and_hashes = set()
    for file_path in file_paths:
        file_name = os.path.basename(file_path)
        file_name_without_ext = os.path.splitext(file_name)[0]
        file_sha256 = sha256_hashes.get(file_name, "")
        if file_sha256: file_sha256 = file_sha256.upper()
        file_names_and_hashes.add((file_name_without_ext, file_sha256))
    
    for item in api_response.get('items', []):
        model_versions = item.get('modelVersions', [])
        
        if not model_versions:
            continue
        
        for idx, model_version in enumerate(model_versions):
            files = model_version.get('files', [])
            match_found = False
            for file_entry in files:
                entry_name = os.path.splitext(file_entry.get('name', ''))[0]
                entry_sha256 = file_entry.get('hashes', {}).get('SHA256', "")
                if entry_sha256: entry_sha256 = entry_sha256.upper()
                
                if (entry_name, entry_sha256) in file_names_and_hashes:
                    match_found = True
                    break
            
            if match_found:
                if idx == 0:
                    updated_models.append((f"&ids={item['id']}", item["name"]))
                else:
                    outdated_models.append((f"&ids={item['id']}", item["name"]))
                break
                
    return updated_models, outdated_models

def get_content_choices(scan_choices=False):
    use_LORA = getattr(opts, "use_LORA", False)
    if use_LORA:
        content_list = ["Checkpoint", "TextualInversion", "LORA & LoCon", "Poses", "Controlnet", "Hypernetwork", "AestheticGradient", "VAE", "Upscaler", "MotionModule", "Wildcards", "Workflows", "Other"]
    else:
        content_list = ["Checkpoint", "TextualInversion", "LORA", "LoCon", "Poses", "Controlnet", "Hypernetwork", "AestheticGradient", "VAE", "Upscaler", "MotionModule", "Wildcards", "Workflows", "Other"]
    if scan_choices:
        content_list.insert(0, 'All')
        return content_list
    return content_list
    
def file_scan(folders, ver_finish, tag_finish, installed_finish, preview_finish, overwrite_toggle, tile_count, gen_hash, progress=gr.Progress() if queue else None):
    global from_ver, from_installed, no_update
    update_log = getattr(opts, "update_log", True)
    gl.scan_files = True
    no_update = False
    if from_ver:
        number = _download.random_number(ver_finish)
    elif from_tag:
        number = _download.random_number(tag_finish)
    elif from_installed:
        number = _download.random_number(installed_finish)
    elif from_preview:
        number = _download.random_number(preview_finish)
    
    if not folders:
        if progress != None:
            progress(0, desc=f"No folder selected.")
        no_update = True
        gl.scan_files = False
        from_ver, from_installed = False, False
        time.sleep(2)
        return (gr.HTML.update(value='<div style="min-height: 0px;"></div>'),
                gr.Textbox.update(value=number))
    
    folders_to_check = []
    if 'All' in folders:
        folders = _file.get_content_choices()
        
    for item in folders:
        if item == "LORA & LoCon":
            folder = _api.contenttype_folder("LORA")
            if folder:
                folders_to_check.append(folder)
            folder = _api.contenttype_folder("LoCon", fromCheck=True)
            if folder:
                folders_to_check.append(folder)
        elif item == "Upscaler":
            folder = _api.contenttype_folder(item, "SwinIR")
            if folder:
                folders_to_check.append(folder)
            folder = _api.contenttype_folder(item, "RealESRGAN")
            if folder:
                folders_to_check.append(folder)
            folder = _api.contenttype_folder(item, "GFPGAN")
            if folder:
                folders_to_check.append(folder)
            folder = _api.contenttype_folder(item, "BSRGAN")
            if folder:
                folders_to_check.append(folder)
            folder = _api.contenttype_folder(item, "ESRGAN")
            if folder:
                folders_to_check.append(folder)
        else:
            folder = _api.contenttype_folder(item)
            if folder:
                folders_to_check.append(folder)
        
    total_files = 0
    files_done = 0
    
    files = list_files(folders_to_check)
    total_files += len(files)
    
    if total_files == 0:
        if progress != None:
            progress(1, desc=f"No files in selected folder.")
        no_update = True
        gl.scan_files = False
        from_ver, from_installed = False, False
        time.sleep(2)
        return (gr.HTML.update(value='<div style="min-height: 0px;"></div>'),
                gr.Textbox.update(value=number))
        
    updated_models = []
    outdated_models = []
    all_model_ids = []
    file_paths = []
    all_ids = []
    
    for file_path in files:
        if gl.cancel_status:
            if progress != None:
                progress(files_done / total_files, desc=f"Processing files cancelled.")
            no_update = True
            gl.scan_files = False
            from_ver, from_installed = False, False
            time.sleep(2)
            return (gr.HTML.update(value='<div style="min-height: 0px;"></div>'),
                    gr.Textbox.update(value=number))
        file_name = os.path.basename(file_path)
        if progress != None:
            progress(files_done / total_files, desc=f"Processing file: {file_name}")
        
        model_id = get_models(file_path, gen_hash)
        if model_id == "offline":
            print("The CivitAI servers did not respond, unable to retrieve Model ID")
        elif model_id == "Model not found" and update_log:
            print(f"model: \"{file_name}\" not found on CivitAI servers.")
        elif model_id != None:
            all_model_ids.append(f"&ids={model_id}")
            all_ids.append(model_id)
            file_paths.append(file_path)
        elif not model_id and update_log:
            print(f"model ID not found for: \"{file_name}\"")
        files_done += 1
        
    all_items = []

    all_model_ids = list(set(all_model_ids))
    
    if not all_model_ids:
        progress(1, desc=f"No model IDs could be retrieved.")
        print("Could not retrieve any Model IDs, please make sure to turn on the \"One-Time Hash Generation for externally downloaded models.\" option if you haven't already.")
        no_update = True
        gl.scan_files = False
        from_ver, from_installed = False, False
        time.sleep(2)
        return (gr.HTML.update(value='<div style="min-height: 0px;"></div>'),
                gr.Textbox.update(value=number))
    
    def chunks(lst, n):
        for i in range(0, len(lst), n):
            yield lst[i:i + n]
            
    if not from_installed:
        model_chunks = list(chunks(all_model_ids, 500))

        base_url = "https://civitai.com/api/v1/models?limit=100"
        url_list = [f"{base_url}{''.join(chunk)}" for chunk in model_chunks]

        url_count = len(all_model_ids) // 100
        if len(all_model_ids) % 100 != 0:
            url_count += 1
        url_done = 0
        api_response = {}
        for url in url_list:
            while url:
                try:
                    if progress is not None:
                        progress(url_done / url_count, desc=f"Sending API request... {url_done}/{url_count}")
                    response = requests.get(url, timeout=(10, 30))
                    if response.status_code == 200:
                        api_response_json = response.json()

                        all_items.extend(api_response_json['items'])
                        metadata = api_response_json.get('metadata', {})
                        url = metadata.get('nextPage', None)
                    elif response.status_code == 503:
                        return  (
                            gr.HTML.update(value=offlineHTML),
                            gr.Textbox.update(value=number)
                        )
                    else:
                        print(f"Error: Received status code {response.status_code} with URL: {url}")
                        url = None
                    url_done += 1
                except requests.exceptions.Timeout:
                    print(f"Request timed out for {url}. Skipping...")
                    url = None
                except requests.exceptions.ConnectionError:
                    print("Failed to connect to the API. The servers might be offline.")
                    url = None
                except Exception as e:
                    print(f"An unexpected error occurred: {e}")
                    url = None
        
        api_response['items'] = all_items
        if api_response['items'] == []:
            return  (
                gr.HTML.update(value=offlineHTML),
                gr.Textbox.update(value=number)
            )
        
    if progress != None:
        progress(1, desc="Processing final results...")
    
    if from_ver:
        updated_models, outdated_models = version_match(file_paths, api_response)
        
        updated_set = set(updated_models)
        outdated_set = set(outdated_models)
        outdated_set = {model for model in outdated_set if model[0] not in {updated_model[0] for updated_model in updated_set}}
        
        all_model_ids = [model[0] for model in outdated_set]
        all_model_names = [model[1] for model in outdated_set]
        
        if update_log:
            for model_name in all_model_names:
                print(f'"{model_name}" is currently outdated.')
        
        if len(all_model_ids) == 0:
            no_update = True
            gl.scan_files = False
            from_ver = False
            return  (
                    gr.HTML.update(value='<div style="font-size: 24px; text-align: center; margin: 50px !important;">No updates found for selected models.</div>'),
                    gr.Textbox.update(value=number)
                )
    
    model_chunks = list(chunks(all_model_ids, tile_count))

    base_url = "https://civitai.com/api/v1/models?limit=100"
    gl.url_list_with_numbers = {i+1: f"{base_url}{''.join(chunk)}" for i, chunk in enumerate(model_chunks)}

    url_error = False
    api_url = gl.url_list_with_numbers.get(1)
    
    if not url_error:
        response = requests.get(api_url, timeout=(10,30))
        try:
            if response.status_code == 200:
                response.encoding = "utf-8"
                gl.ver_json = json.loads(response.text)
                
                highest_number = max(gl.url_list_with_numbers.keys())
                gl.ver_json["metadata"]["totalPages"] = highest_number
                
                if highest_number > 1:
                    gl.ver_json["metadata"]["nextPage"] = gl.url_list_with_numbers.get(2)
            else:
                print(f"Error: Received status code {response.status_code} for URL: {url}")
                url_error = True
        except requests.exceptions.Timeout:
            print(f"Request timed out for {url}. Skipping...")
            url_error = True
        except requests.exceptions.ConnectionError:
            print("Failed to connect to the API. The servers might be offline.")
            url_error = True
        except Exception as e:  
            print(f"An unexpected error occurred: {e}")
            url_error = True
        
    if url_error:
        gl.scan_files = False
        return  (
                gr.HTML.update(value=offlineHTML),
                gr.Textbox.update(value=number)
            )
    elif from_ver:
        gl.scan_files = False
        return  (
                gr.HTML.update(value='<div style="font-size: 24px; text-align: center; margin: 50px !important;">Outdated models have been found.<br>Please press the button above to load the models into the browser tab</div>'),
                gr.Textbox.update(value=number)
            )

    elif from_installed:
        gl.scan_files = False
        return  (
                gr.HTML.update(value='<div style="font-size: 24px; text-align: center; margin: 50px !important;">Installed models have been loaded.<br>Please press the button above to load the models into the browser tab</div>'),
                gr.Textbox.update(value=number)
            )

    elif from_tag:
        for file_path, id_value in zip(file_paths, all_ids):
            install_path, file_name = os.path.split(file_path)
            model_versions = _api.update_model_versions(id_value, api_response)
            preview_html = _api.update_model_info(None, model_versions.get('value'), True, id_value, api_response)
            sub_folder = os.path.normpath(os.path.relpath(install_path, gl.main_folder))
            save_model_info(install_path, file_name, sub_folder, preview_html=preview_html, api_response=api_response, overwrite_toggle=overwrite_toggle)
        if progress != None:
            progress(1, desc=f"All tags succesfully saved!")
        gl.scan_files = False
        time.sleep(2)
        return  (
                gr.HTML.update(value='<div style="min-height: 0px;"></div>'),
                gr.Textbox.update(value=number)
            )
    
    elif from_preview:
        completed_preview = 0
        preview_count = len(file_paths)
        for file in file_paths:
            _, file_name = os.path.split(file)
            name = os.path.splitext(file_name)[0]
            if progress != None:
                progress(completed_preview / preview_count, desc=f"Saving preview images... {completed_preview}/{preview_count} | {name}")
            save_preview(file, api_response, overwrite_toggle)
            completed_preview += 1
        gl.scan_files = False
        return  (
                gr.HTML.update(value='<div style="min-height: 0px;"></div>'),
                gr.Textbox.update(value=number)
            )
    
def save_tag_start(tag_start):
    global from_tag, from_ver, from_installed, from_preview
    from_tag, from_ver, from_installed, from_preview = True, False, False, False
    number = _download.random_number(tag_start)
    return (
        gr.Textbox.update(value=number),
        gr.Button.update(interactive=False, visible=False),
        gr.Button.update(interactive=True, visible=True),
        gr.Button.update(interactive=False, visible=True),
        gr.Button.update(interactive=False, visible=True),
        gr.Button.update(interactive=False, visible=True),
        gr.HTML.update(value='<div style="min-height: 100px;"></div>')
    )
    
def save_preview_start(preview_start):
    global from_tag, from_ver, from_installed, from_preview
    from_preview, from_tag, from_ver, from_installed = True, False, False, False
    number = _download.random_number(preview_start)
    return (
        gr.Textbox.update(value=number),
        gr.Button.update(interactive=False, visible=False),
        gr.Button.update(interactive=True, visible=True),
        gr.Button.update(interactive=False, visible=True),
        gr.Button.update(interactive=False, visible=True),
        gr.Button.update(interactive=False, visible=True),
        gr.HTML.update(value='<div style="min-height: 100px;"></div>')
    )

def installed_models_start(installed_start):
    global from_installed, from_ver, from_tag, from_preview
    from_installed, from_ver, from_tag, from_preview = True, False, False, False
    number = _download.random_number(installed_start)
    return (
        gr.Textbox.update(value=number),
        gr.Button.update(interactive=False, visible=False),
        gr.Button.update(interactive=True, visible=True),
        gr.Button.update(interactive=False, visible=True),
        gr.Button.update(interactive=False, visible=True),
        gr.Button.update(interactive=False, visible=True),
        gr.HTML.update(value='<div style="min-height: 100px;"></div>')
    )

def ver_search_start(ver_start):
    global from_ver, from_tag, from_installed, from_preview
    from_ver, from_tag, from_installed, from_preview = True, False, False, False
    number = _download.random_number(ver_start)
    return (
        gr.Textbox.update(value=number),
        gr.Button.update(interactive=False, visible=False),
        gr.Button.update(interactive=True, visible=True),
        gr.Button.update(interactive=False, visible=True),
        gr.Button.update(interactive=False, visible=True),
        gr.Button.update(interactive=False, visible=True),
        gr.HTML.update(value='<div style="min-height: 100px;"></div>')
    )

def save_tag_finish():
    global from_tag
    from_tag = False
    return (
        gr.Button.update(interactive=True, visible=True),
        gr.Button.update(interactive=True, visible=True),
        gr.Button.update(interactive=True, visible=True),
        gr.Button.update(interactive=True, visible=True),
        gr.Button.update(interactive=False, visible=False)
    )

def save_preview_finish():
    global from_preview
    from_preview = False
    return (
        gr.Button.update(interactive=True, visible=True),
        gr.Button.update(interactive=True, visible=True),
        gr.Button.update(interactive=True, visible=True),
        gr.Button.update(interactive=True, visible=True),
        gr.Button.update(interactive=False, visible=False)
    )

def scan_finish():
    return (
        gr.Button.update(interactive=no_update, visible=no_update),
        gr.Button.update(interactive=no_update, visible=no_update),
        gr.Button.update(interactive=no_update, visible=no_update),
        gr.Button.update(interactive=no_update, visible=no_update),
        gr.Button.update(interactive=False, visible=False),
        gr.Button.update(interactive=not no_update, visible=not no_update)
    )

def load_to_browser(content_type, sort_type, period_type, use_search_term, search_term, tile_count, base_filter, nsfw):
    global from_ver, from_installed
    if from_ver:
        model_list_return = _api.update_model_list(from_ver=True, tile_count=tile_count)
    if from_installed:
        model_list_return = _api.update_model_list(from_installed=True, tile_count=tile_count)
    
    use_LORA = getattr(opts, "use_LORA", False)
    if content_type:
        if use_LORA and 'LORA & LoCon' in content_type:
            content_type.remove('LORA & LoCon')
            if 'LORA' not in content_type:
                content_type.append('LORA')
            if 'LoCon' not in content_type:
                content_type.append('LoCon')
    
    current_inputs = (content_type, sort_type, period_type, use_search_term, search_term, tile_count, base_filter, nsfw)
    gl.previous_inputs = current_inputs
    
    gl.file_scan = True
    from_ver, from_installed = False, False
    return (
        *model_list_return,
        gr.Button.update(interactive=True, visible=True),
        gr.Button.update(interactive=True, visible=True),
        gr.Button.update(interactive=True, visible=True),
        gr.Button.update(interactive=True, visible=True),
        gr.Button.update(interactive=False, visible=False),
        gr.Button.update(interactive=False, visible=False),
        gr.HTML.update(value='<div style="min-height: 0px;"></div>')
    )
    
def cancel_scan():
    gl.cancel_status = True
    
    while True:
        if not gl.scan_files:
            gl.cancel_status = False
            return
        else:
            time.sleep(0.5)
            continue
