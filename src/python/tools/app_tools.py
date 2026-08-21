import subprocess
import json
import os

def search_installed_apps(keyword: str):
    try:
        cmd = f'powershell "Get-StartApps | Where-Object {{ $_.Name -like \'*{keyword}*\' }} | Select-Object Name, AppID | ConvertTo-Json"'
        output = subprocess.check_output(cmd, shell=True, text=True).strip()

        if not output:
            return f"No installed application found matching '{keyword}'."

        apps = json.loads(output)
        if isinstance(apps, dict):
            apps = [apps]

        results = [
            f"Name: {app['Name']} (AppID: {app.get('AppID', '')})"
            for app in apps
        ]
        return "\n".join(results)
    except Exception as e:
        return f"Error searching apps: {e}"

def launch_app(app_name_or_path):
    if isinstance(app_name_or_path, (set, list, tuple)):
        app_name_or_path = next(iter(app_name_or_path), "")
    elif isinstance(app_name_or_path, dict):
        app_name_or_path = app_name_or_path.get("app_name_or_path", next(iter(app_name_or_path.values()), ""))

    app_str = str(app_name_or_path).strip("'\" ")
    common_apps = {
        "notepad": "notepad.exe",
        "calc": "calc.exe",
        "cmd": "cmd.exe",
        "mspaint": "mspaint.exe"
    }
    if app_str.lower() in common_apps:
        target = common_apps[app_str.lower()]
        try:
            subprocess.Popen(target, shell=True)
            return f"Successfully launched common app: {target}"
        except Exception:
            pass

    try:
        cmd = f'powershell "Get-StartApps | Where-Object {{ $_.Name -like \'*{app_str}*\' }} | Select-Object Name, AppID | ConvertTo-Json"'
        output = subprocess.check_output(cmd, shell=True, text=True).strip()
        if output:
            data = json.loads(output)
            if isinstance(data, dict):
                data = [data]
            if data and "AppID" in data[0]:
                appid = data[0]["AppID"]
                subprocess.Popen(f'explorer.exe "shell:AppsFolder\\{appid}"')
                return f"Successfully launched installed app '{data[0]['Name']}' (AppID: {appid})"
    except Exception:
        pass

    try:
        subprocess.Popen(app_str, shell=True)
        return f"Successfully launched via shell: {app_str}"
    except Exception:
        pass

    try:
        os.startfile(app_str)
        return f"Successfully started: {app_str}"
    except Exception as e:
        return f"Failed to launch app '{app_str}': {e}"
