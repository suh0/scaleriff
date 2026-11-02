@echo off
rem ScaleRiff 설치: uv로 .venv(Python 3.12) + 의존성, MSVC Build Tools가 있으면 madmom까지.
rem 사용: setup.bat   (madmom 건너뛰기: set SCALERIFF_NO_MADMOM=1 후 실행)
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "PY=.venv\Scripts\python.exe"

set "UV=uv"
where uv >nul 2>nul || set "UV=%USERPROFILE%\.local\bin\uv.exe"
if not "%UV%"=="uv" if not exist "%UV%" goto :no_uv

if not exist "%PY%" "%UV%" venv --python 3.12 .venv || goto :fail
"%UV%" pip install --python "%PY%" -r requirements.txt -c requirements-tested.txt || goto :fail

if defined SCALERIFF_NO_MADMOM goto :no_madmom
set "VCVARS="
for %%R in ("%ProgramFiles(x86)%" "%ProgramFiles%") do for /d %%V in ("%%~R\Microsoft Visual Studio\*") do for /d %%E in ("%%~V\*") do if exist "%%~E\VC\Auxiliary\Build\vcvars64.bat" set "VCVARS=%%~E\VC\Auxiliary\Build\vcvars64.bat"
if not defined VCVARS goto :no_madmom

echo [madmom] MSVC로 소스 빌드: %VCVARS%
call "%VCVARS%" >nul
set DISTUTILS_USE_SDK=1
set MSSdk=1
"%UV%" pip install --python "%PY%" "setuptools<81" wheel Cython -c requirements-tested.txt || goto :fail
"%UV%" pip install --python "%PY%" --no-build-isolation madmom==0.16.1 -c requirements-tested.txt || goto :fail
rem numpy 2.0은 불균일 배열을 거부 — downbeats.py 한 줄 패치(이미 고쳐져 있으면 그대로)
"%PY%" -c "import importlib.util as u, pathlib; p = pathlib.Path(u.find_spec('madmom').submodule_search_locations[0], 'features', 'downbeats.py'); s = p.read_text(encoding='utf-8'); p.write_text(s.replace('np.argmax(np.asarray(results)[:, 1])', 'int(np.argmax([r[1] for r in results]))'), encoding='utf-8')" || goto :fail
goto :check

:no_madmom
echo [madmom] 건너뜀 - librosa 분석으로 동작합니다. (madmom: Visual Studio Build Tools의 C++ 빌드 도구 설치 후 setup.bat 재실행)

:check
"%PY%" -c "from ingest._madmom_compat import HAS_MADMOM; print('[분석 엔진]', 'madmom' if HAS_MADMOM else 'librosa')" || goto :fail
where deno >nul 2>nul && goto :done
if exist "%LOCALAPPDATA%\Microsoft\WinGet\Packages\DenoLand.Deno_*" goto :done
echo [YouTube] Deno가 없습니다. 유튜브 링크 입력에 필요: winget install DenoLand.Deno

:done
echo 설치 완료. 실행: %PY% main.py
exit /b 0

:no_uv
echo uv가 필요합니다. PowerShell에서 설치 후 새 창에서 다시 실행하세요:
echo   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
exit /b 1

:fail
echo 설치 실패 - 위 오류를 확인하세요.
exit /b 1
