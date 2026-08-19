@echo off
REM 一键打包 WordLookup.exe（适用于 Windows）
REM 前置：.venv 已激活，已执行 pip install -r requirements.txt pyinstaller python-lzo

echo [1/2] 安装打包依赖...
pip install --quiet -r requirements.txt pyinstaller python-lzo 2>nul

echo [2/2] 打包中...
pyinstaller --noconfirm wordlookup.spec

echo.
echo 完成！可执行文件在 dist\WordLookup.exe
echo 首次运行时选择你的 .mdx 词典即可自动构建。
pause