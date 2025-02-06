import urllib.request
import re
import json_repair
import os
import json5
from mdutils.mdutils import MdUtils
import pandas as pd
import defusedxml.ElementTree as ET

# https://stackoverflow.com/a/18381470 (Onur Yıldırım, CC BY-SA 4.0)
def remove_comments(string):
    pattern = r"(\".*?\"|\'.*?\')|(/\*.*?\*/|//[^\r\n]*$)"
    # first group captures quoted strings (double or single)
    # second group captures comments (//single-line or /* multi-line */)
    regex = re.compile(pattern, re.MULTILINE|re.DOTALL)
    def _replacer(match):
        # if the 2nd group (capturing comments) is not None,
        # it means we have captured a non-quoted (real) comment string.
        if match.group(2) is not None:
            return "" # so we will return empty to remove the comment
        else: # otherwise, we will return the 1st group
            return match.group(1) # captured quoted-string
    return regex.sub(_replacer, string)

def load_vcmi_json(string):
    try:
        obj = json5.loads(string)
    except:
        tmp = remove_comments(string.decode())
        obj = json_repair.loads(tmp)

    return obj

def get_languages():
    with urllib.request.urlopen('https://raw.githubusercontent.com/vcmi/vcmi/develop/lib/texts/Languages.h') as f:
        src = f.read().decode('utf-8')
    languages = [x for x in re.findall(r"{ ?\"([\w]*)?\" ?,", src, re.IGNORECASE) if "other" not in x]
    return languages

def get_base_mod():
    return load_vcmi_json(urllib.request.urlopen('https://raw.githubusercontent.com/vcmi/vcmi/develop/Mods/vcmi/mod.json').read())

def base_mod_existing(languages):
    vcmi_base_mod = get_base_mod()
    return {value:(value in vcmi_base_mod) for value in languages}

def base_mod_ratio(languages):
    base_mod = get_base_mod()
    translation_english = load_vcmi_json(urllib.request.urlopen('https://raw.githubusercontent.com/vcmi/vcmi/develop/Mods/vcmi/Content/' + base_mod["translations"][0]).read())

    data = {}

    for language in [key for key, value in base_mod_existing(languages).items() if value == True]:
        translation = load_vcmi_json(urllib.request.urlopen('https://raw.githubusercontent.com/vcmi/vcmi/develop/Mods/vcmi/Content/' + next(value for key, value in base_mod.items() if key == language)["translations"][0]).read())
        count_equal = 0
        count_difference = 0
        count_only_english = 0
        for key, value in translation_english.items():
            if key not in translation:
                count_only_english += 1
                continue
            if translation[key] == value:
                count_equal += 1
            else:
                count_difference += 1
        ratio = (count_difference + count_equal) / len(translation_english)
        data[language] = {"ratio": ratio, "count_equal": count_equal, "count_difference": count_difference, "count_only_english": count_only_english}
    return data

def get_mod_repo():
    settings_schema = load_vcmi_json(urllib.request.urlopen("https://raw.githubusercontent.com/vcmi/vcmi/develop/config/schemas/settings.json").read())
    vcmi_mod_url = settings_schema["properties"]["launcher"]["properties"]["defaultRepositoryURL"]["default"]
    vcmi_mods = load_vcmi_json(urllib.request.urlopen(vcmi_mod_url).read())
    return vcmi_mods

def get_translation_mods():
    vcmi_translation_mods = {}

    vcmi_mods = get_mod_repo()

    for key, value in vcmi_mods.items():
        url = value["mod"].replace(" ", "%20")
        mod = load_vcmi_json(urllib.request.urlopen(url).read())
        if "language" in mod and "modType" in mod and mod["modType"].lower() == "translation":
            vcmi_translation_mods[mod["language"]] = (url, mod)

    return vcmi_translation_mods

def get_translation_mods_translation():
    translation_mods = get_translation_mods()
    data = {}

    for key, value in translation_mods.items():
        print(f"\n--- Processing language: {key} ---")
        tmp = {}
        chronicles_found = False

        for item in value[1]["translations"]:
            base_url = value[0].rsplit('/', 1)[0] + "/content/"
            print(f"Checking base translation file: {base_url + item}")

            try:
                tmp_str = urllib.request.urlopen(base_url + item).read()
            except Exception as e:
                print(f"Error reading {base_url + item}: {e}")
                continue

            if "chronicles.json" in item:
                print(f"Found chronicles.json in: {base_url + item}")
                chronicles_data = load_vcmi_json(tmp_str)
                prefixed_chronicles = {f"chronicles.{k}": v for k, v in chronicles_data.items()}
                tmp |= prefixed_chronicles
                chronicles_found = True
            else:
                tmp |= load_vcmi_json(tmp_str)

        if not chronicles_found:
            try:
                repo_url_parts = value[0].split("/")
                repo_owner = repo_url_parts[3]
                repo_name = repo_url_parts[4]
                branch_name = repo_url_parts[5]
                api_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/git/trees/{branch_name}?recursive=1"

                print(f"Fetching repo structure from: {api_url}")
                response = urllib.request.urlopen(api_url).read()
                repo_files = json5.loads(response)["tree"]

                chronicles_json_files = [
                    f["path"] for f in repo_files
                    if "chronicles" in f["path"] 
                    and f["path"].endswith(".json") 
                    and "video" not in f["path"].lower() 
                    and not f["path"].endswith("mod.json")
                ]

                print(f"Found chronicles JSON files: {chronicles_json_files}")

                for json_file in chronicles_json_files:
                    json_file_url = f"https://raw.githubusercontent.com/{repo_owner}/{repo_name}/{branch_name}/{json_file}"
                    print(f"Fetching JSON file: {json_file_url}")

                    try:
                        tmp_str = urllib.request.urlopen(json_file_url).read()
                        chronicles_data = load_vcmi_json(tmp_str)
                        prefixed_chronicles = {f"chronicles.{k}": v for k, v in chronicles_data.items()}
                        tmp |= prefixed_chronicles
                    except Exception as e:
                        print(f"Error reading JSON file {json_file_url}: {e}")
            except Exception as e:
                print(f"Error processing chronicles JSON files for {key}: {e}")

        data[key] = tmp

    return data

def get_translation_mods_translation_assets():
    translation_mods = get_translation_mods()
    data = {}
    for key, value in translation_mods.items():
        repo = re.search(r"vcmi-mods\/(.*?)\/", value[0]).group(1)
        branch = re.search(repo + r"\/([^\/]*?)\/", value[0]).group(1)
        files_api = "https://api.github.com/repos/vcmi-mods/" + repo + "/git/trees/" + branch + "?recursive=1"
        files = [x["path"].lower() for x in json5.loads(urllib.request.urlopen(files_api).read())["tree"]]
        files_filtered = [x for x in files if "mods/" not in x]

        files_to_translate = json5.load(open("files_to_translated.json", "r"))
        files_ct = {}
        files_found = {}
        for file in files_to_translate:
            type = re.search(r"content\/(.*?)\/", file).group(1)
            if type not in files_ct: files_ct[type] = 0
            if type not in files_found: files_found[type] = 0
            files_ct[type] += 1
            files_found[type] += 1 if any(file in x for x in files_filtered) else 0
        files_ratio = {k: files_found[k]/v for k, v in files_ct.items()}

        data[key] = files_ratio
    return data

def translation_mod_ratio(translation_mods_translation):
    translation_english = translation_mods_translation["english"]

    data = {}

    for language in [key for key, value in translation_mods_translation.items() if key != "english"]:
        data_ns = {}
        namespaces = [None, "map", "campaign", "chronicles"]
        for namespace in namespaces:
            translation = translation_mods_translation[language]
            count_equal = 0
            count_difference = 0
            count_only_english = 0
            for key, value in translation_english.items():
                if key.split(".", 1)[0] == namespace or (namespace == None and key.split(".", 1)[0] not in namespaces):
                    if key not in translation:
                        count_only_english += 1
                        continue
                    if translation[key] == value:
                        count_equal += 1
                    else:
                        count_difference += 1
            ratio = (count_difference + count_equal) / (count_only_english + count_difference + count_equal)
            data_ns[namespace] = {"ratio": ratio, "count_equal": count_equal, "count_difference": count_difference, "count_only_english": count_only_english}
        data[language] = data_ns
    return data

def get_qt_translations(languages):
    data = {}

    for language in [key for key, value in base_mod_existing(languages).items() if value == True]:
        data_type = {}
        for type in ["mapeditor", "launcher"]:
            count_translated = 0
            count_untranslated = 0
            try:
                tmp_str = urllib.request.urlopen("https://raw.githubusercontent.com/vcmi/vcmi/develop/" + type + "/translation/" + language + ".ts").read()
            except:
                tmp_str = ""
            if tmp_str != "":
                root = ET.fromstring(tmp_str)
                for item_context in root.iter('context'):
                    for item_message in item_context.iter('message'):
                        if list(item_message.iter('translation'))[0].get("type") == None:
                            count_translated += 1
                        else:
                            count_untranslated += 1
            if (count_translated + count_untranslated) > 0:
                ratio = (count_translated) / (count_translated + count_untranslated)
            else:
                ratio = 0
            data_type[type] = {"ratio": ratio, "count_translated": count_translated, "count_untranslated": count_untranslated}
        data[language] = data_type
    return data

def get_mod_translations(languages):
    vcmi_mods = get_mod_repo()
    data = {}
    for key, value in vcmi_mods.items():
        url = value["mod"].replace(" ", "%20")
        mod = load_vcmi_json(urllib.request.urlopen(url).read())
        mod_name = mod.get("name", key)
        mod_type = mod.get("modType", "unknown").lower()

        if mod_type == "translation":
            continue

        found_languages = []
        for language in languages:
            if language in mod:
                found_languages.append(language)

        data[key] = {"name": mod_name, "modType": mod_type, "languages": found_languages}
    return data

def create_md():
    languages = get_languages()
    languages_translate = [x for x in languages if x != "english"]

    md = MdUtils(file_name='_')

    def format_value(percent):
        if percent < 0.7:
            return "$\\color{red}{\\textsf{" + str(round(percent * 100, 1)) + " \\%" + "}}$"
        elif percent < 0.9:
            return "$\\color{orange}{\\textsf{" + str(round(percent * 100, 1)) + " \\%" + "}}$"
        else:
            return "$\\color{green}{\\textsf{" + str(round(percent * 100, 1)) + " \\%" + "}}$"

    md.new_header(level=1, title="VCMI translations")
    md.new_line("This tables shows the current translation progress of VCMI. See [here](https://vcmi.eu/translators/Translations/) how to translate VCMI. See assets for translation [here](files_to_translated.json) (not every language need each asset).")

    md.new_header(level=2, title="Main translation")
    tmp = base_mod_ratio(languages_translate)
    df = pd.DataFrame({"Area": "[Main-Repo](https://github.com/vcmi/vcmi)"} | {x:([format_value(tmp[x]["ratio"])] if x in tmp else [format_value(0)]) for x in languages_translate})
    tmp = translation_mod_ratio(get_translation_mods_translation())
    for area in list(tmp.values())[0].keys():
        df = pd.concat([df, pd.DataFrame({"Area": "[Mod-Repo](https://github.com/vcmi-mods)" + (' game' if area == None else ' ' + area)} | {x:([format_value(tmp[x][area]["ratio"])] if x in tmp else [format_value(0)]) for x in languages_translate})], ignore_index=True)
    tmp = get_translation_mods_translation_assets()
    for area in list(tmp.values())[0].keys():
        df = pd.concat([df, pd.DataFrame({"Area": "[Mod-Repo](https://github.com/vcmi-mods)" + (' Assets: ' + area)} | {x:([format_value(tmp[x][area])] if x in tmp else [format_value(0)]) for x in languages_translate})], ignore_index=True)
    df = df.T.reset_index().T
    md.new_table(columns=df.shape[1], rows=df.shape[0], text=df.to_numpy().flatten(), text_align='center')

    md.new_header(level=2, title="QT tools translation")
    tmp = get_qt_translations(languages_translate)
    df = pd.DataFrame(columns=["Tool"] + languages_translate)
    for tool in list(tmp.values())[0].keys():
        df = pd.concat([df, pd.DataFrame({"Tool": "[" + tool + "](https://github.com/vcmi/vcmi/tree/develop/" + tool + "/translation)"} | {x:[format_value(tmp[x][tool]["ratio"])] if x in tmp else [format_value(0)] for x in languages_translate})], ignore_index=True)
    df = df.T.reset_index().T
    md.new_table(columns=df.shape[1], rows=df.shape[0], text=df.to_numpy().flatten(), text_align='center')

    tmp = get_mod_translations(languages_translate)
    mod_counts = {language: sum(1 for mods in tmp.values() if language in mods["languages"]) for language in languages_translate}
    total_mods = len(tmp)
    percentages = [mod_counts[lang] / total_mods if total_mods > 0 else 0 for lang in languages_translate]
    
    md.new_header(level=2, title="Mods translation status")
    header = ["Language"] + languages_translate
    values = ["Translated mods"] + [format_value(percent) for percent in percentages]
    
    md.new_table(columns=len(header), rows=2, text=header + values, text_align='center')

    md.new_header(level=2, title="Mods translation details")
    tmp = get_mod_translations(languages_translate)
    df = pd.DataFrame(columns=["Mod", "Type"] + languages_translate)

    for mod, mod_data in tmp.items():
        df = pd.concat([df, pd.DataFrame({"Mod": "[" + mod_data["name"] + "](https://github.com/vcmi-mods/" + mod.replace(" ", "-") + ")", "Type": mod_data["modType"], **{x: ["x" if x in mod_data["languages"] else ""] for x in languages_translate}})], ignore_index=True)

    df = df.sort_values(by=["Type", "Mod"])

    df = df.T.reset_index().T
    md.new_table(columns=df.shape[1], rows=df.shape[0], text=df.to_numpy().flatten(), text_align='center')

    return md.get_md_text()

if __name__ == "__main__":
    with open(os.path.join('.', 'README.md'), "w") as f:
        f.write(create_md())
