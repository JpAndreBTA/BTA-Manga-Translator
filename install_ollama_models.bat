@echo off
setlocal
title BTA MangaTranslate - Install Ollama Models

echo.
echo === BTA MangaTranslate - Ollama model setup ===
echo.

set "OLLAMA_EXE="
for %%P in (
  "%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
  "%ProgramFiles%\Ollama\ollama.exe"
  "%ProgramFiles(x86)%\Ollama\ollama.exe"
) do (
  if exist "%%~P" set "OLLAMA_EXE=%%~P"
)

if not defined OLLAMA_EXE (
  for /f "delims=" %%P in ('where ollama 2^>nul') do (
    if not defined OLLAMA_EXE set "OLLAMA_EXE=%%~P"
  )
)

if not defined OLLAMA_EXE (
  echo Ollama was not found locally.
  where winget >nul 2>nul
  if errorlevel 1 (
    echo [ERROR] Ollama is not installed and winget is not available for automatic install.
    echo Install it from https://ollama.com/download/windows
    echo Then open Ollama once and run this file again.
    pause
    exit /b 1
  )

  echo Trying to install Ollama automatically with winget...
  winget install --id Ollama.Ollama -e --source winget --accept-package-agreements --accept-source-agreements
  if errorlevel 1 (
    echo [ERROR] Automatic Ollama install failed.
    echo Install it manually from https://ollama.com/download/windows
    echo Then open Ollama once and run this file again.
    pause
    exit /b 1
  )

  for %%P in (
    "%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
    "%ProgramFiles%\Ollama\ollama.exe"
    "%ProgramFiles(x86)%\Ollama\ollama.exe"
  ) do (
    if exist "%%~P" set "OLLAMA_EXE=%%~P"
  )

  if not defined OLLAMA_EXE (
    for /f "delims=" %%P in ('where ollama 2^>nul') do (
      if not defined OLLAMA_EXE set "OLLAMA_EXE=%%~P"
    )
  )
)

if not defined OLLAMA_EXE (
  echo [ERROR] Ollama was installed but the executable was not found yet.
  echo Close this window, open Ollama from the Start menu, then run this file again.
  pause
  exit /b 1
)

echo Found Ollama: %OLLAMA_EXE%

"%OLLAMA_EXE%" list >nul 2>nul
if errorlevel 1 (
  echo Ollama service is not responding. Trying to start it...
  start "" "%OLLAMA_EXE%" serve
  timeout /t 8 /nobreak >nul
)

"%OLLAMA_EXE%" list >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Ollama was found but the local service is still not responding.
  echo Open Ollama from the Windows Start menu, wait a few seconds, then run this file again.
  echo If it still fails, restart Windows after installing Ollama.
  pause
  exit /b 1
)

echo [1/2] Pulling OCR model: glm-ocr
"%OLLAMA_EXE%" pull glm-ocr
if errorlevel 1 goto failed

echo.
echo [2/2] Pulling default vision/translation model: gemma3:4b
"%OLLAMA_EXE%" pull gemma3:4b
if errorlevel 1 goto failed

echo.
echo [OK] Ollama models are ready.
echo You can now run run.bat and use the Chrome extension.
pause
exit /b 0

:failed
echo.
echo [ERROR] A model download failed.
echo Check your internet connection and free disk space, then run this file again.
pause
exit /b 1
