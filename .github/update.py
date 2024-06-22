import urllib.request
import re
import json_repair
import os
import json5
import xml.etree.ElementTree as ET
from mdutils.mdutils import MdUtils
import pandas as pd

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
    with urllib.request.urlopen('https://raw.githubusercontent.com/vcmi/vcmi/develop/lib/Languages.h') as f:
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
    translation_english = load_vcmi_json(urllib.request.urlopen('https://raw.githubusercontent.com/vcmi/vcmi/develop/Mods/vcmi/' + base_mod["translations"][0]).read())

    data = {}

    for language in [key for key, value in base_mod_existing(languages).items() if value == True]:
        translation = load_vcmi_json(urllib.request.urlopen('https://raw.githubusercontent.com/vcmi/vcmi/develop/Mods/vcmi/' + next(value for key, value in base_mod.items() if key == language)["translations"][0]).read())
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
        if "language" in mod:
            vcmi_translation_mods[mod["language"]] = (url, mod)

    return vcmi_translation_mods

def get_translation_mods_translation():
    translation_mods = get_translation_mods()
    data = {}
    for key, value in translation_mods.items():
        tmp = {}
        for item in value[1]["translations"]:
            base_url = value[0].rsplit('/', 1)[0] + "/content/"
            try:
                tmp_str = urllib.request.urlopen(base_url + item).read()
            except:
                tmp_str = urllib.request.urlopen((base_url + item).replace("content", "Content").replace("config", "Config")).read()
            tmp |= load_vcmi_json(tmp_str)
        data[key] = tmp
    return data

def translation_mod_ratio(translation_mods_translation):
    translation_english = translation_mods_translation["english"]

    data = {}

    for language in [key for key, value in translation_mods_translation.items() if key != "english"]:
        data_ns = {}
        namespaces = [None, "map", "campaign"]
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
            tmp_str = urllib.request.urlopen("https://raw.githubusercontent.com/vcmi/vcmi/develop/" + type + "/translation/" + language + ".ts").read()
            root = ET.fromstring(tmp_str)
            for item_context in root.iter('context'):
                for item_message in item_context.iter('message'):
                    if list(item_message.iter('translation'))[0].get("type") == None:
                        count_translated += 1
                    else:
                        count_untranslated += 1
            ratio = (count_translated) / (count_translated + count_untranslated)
            data_type[type] = {"ratio": ratio, "count_translated": count_translated, "count_untranslated": count_untranslated}
        data[language] = data_type
    return data

def get_mod_translations(languages):
    vcmi_mods = get_mod_repo()
    data = {}
    for key, value in vcmi_mods.items():
        url = value["mod"].replace(" ", "%20")
        mod = load_vcmi_json(urllib.request.urlopen(url).read())
        if "language" not in mod:
            found_languages = []
            for language in languages:
                if language in mod:
                    found_languages.append(language)
            data[key] = found_languages
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
    md.new_line("This tables shows the current translation progress of VCMI. Contains only the state of the translation strings, not for the assets. See [here](https://github.com/vcmi/vcmi/blob/develop/docs/modders/Translations.md) how to translate VCMI.")

    md.new_header(level=2, title="Main translation")
    tmp = base_mod_ratio(languages_translate)
    df = pd.DataFrame({"Area": "[Main-Repo](https://github.com/vcmi/vcmi)"} | {x:([format_value(tmp[x]["ratio"])] if x in tmp else [format_value(0)]) for x in languages_translate})
    tmp = translation_mod_ratio(get_translation_mods_translation())
    for area in list(tmp.values())[0].keys():
        df = pd.concat([df, pd.DataFrame({"Area": "[Mod-Repo](https://github.com/vcmi-mods)" + (' main' if area == None else ' ' + area)} | {x:([format_value(tmp[x][area]["ratio"])] if x in tmp else [format_value(0)]) for x in languages_translate})], ignore_index=True)
    df = df.T.reset_index().T
    md.new_table(columns=df.shape[1], rows=df.shape[0], text=df.to_numpy().flatten(), text_align='center')

    md.new_header(level=2, title="QT tools translation")
    tmp = get_qt_translations(languages_translate)
    df = pd.DataFrame(columns=["Tool"] + languages_translate)
    for tool in list(tmp.values())[0].keys():
        df = pd.concat([df, pd.DataFrame({"Tool": "[" + tool + "](https://github.com/vcmi/vcmi/tree/develop/" + tool + "/translation)"} | {x:[format_value(tmp[x][tool]["ratio"])] if x in tmp else [format_value(0)] for x in languages_translate})], ignore_index=True)
    df = df.T.reset_index().T
    md.new_table(columns=df.shape[1], rows=df.shape[0], text=df.to_numpy().flatten(), text_align='center')

    md.new_header(level=2, title="Mod translations")
    tmp = get_mod_translations(languages_translate)
    df = pd.DataFrame(columns=["Mod"] + languages_translate)
    for mod in tmp:
        df = pd.concat([df, pd.DataFrame({"Mod": "[" + mod + "](https://github.com/vcmi-mods/" + mod + ")"} | {x:["x" if x in tmp[mod] else ""] for x in languages_translate})], ignore_index=True)
    df = df.T.reset_index().T
    md.new_table(columns=df.shape[1], rows=df.shape[0], text=df.to_numpy().flatten(), text_align='center')

    return md.get_md_text()

if __name__ == "__main__":
    with open(os.path.join('.', 'README.md'), "w") as f:
        f.write(create_md())
