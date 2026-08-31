@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0\.."
chcp 65001 >nul

set "SAFE_DIR=D:/___TOOLS/_Tinix FB Down"
set "TOOLS_DIR=%~dp0"
set "SCOPE_FILE=%TOOLS_DIR%skill-scope.txt"
set "PRESET_ROOT=%TOOLS_DIR%presets"
set "EXPORT_ROOT=%TOOLS_DIR%exports"
set "SKILL_SCOPE=core\fanpage_scanner.py gui\account_manager.py .agent\skills\scan_fanpage_account"
if exist "%SCOPE_FILE%" (
  set /p SKILL_SCOPE=<"%SCOPE_FILE%"
)

:menu
cls
echo ==========================================
echo   Tinix _Skill tools
echo ==========================================
echo   Active scope: %SKILL_SCOPE%
echo   1. Status
echo   2. New branch
echo   3. Checkpoint commit
echo   4. Restore files
echo   5. Checkpoints
echo   6. Run app
echo   7. Preset
echo   8. Create skill
echo   9. Remove skill
echo   M. Branch manager
echo   0. Exit
echo.
choice /c 123456789M0 /n /m "Choose an option: "
if errorlevel 11 goto :eof
if errorlevel 10 goto branch_menu
if errorlevel 9 goto remove_skill
if errorlevel 8 goto create_skill
if errorlevel 7 goto preset_menu
if errorlevel 6 goto run_app
if errorlevel 5 goto git_log
if errorlevel 4 goto restore_files
if errorlevel 3 goto checkpoint_commit
if errorlevel 2 goto new_branch
if errorlevel 1 goto status
goto menu

:git
git -c safe.directory="%SAFE_DIR%" %*
exit /b %errorlevel%

:restore_scope
git -c safe.directory="%SAFE_DIR%" restore --staged --worktree %*
exit /b %errorlevel%

:status
git -c safe.directory="%SAFE_DIR%" status --short
echo.
echo Current branch:
set "CURRENT_BRANCH="
set "BRANCH_STATE_FILE=%TEMP%\tinix_branch_state.txt"
git -c safe.directory="%SAFE_DIR%" branch > "%BRANCH_STATE_FILE%"
for /f "usebackq delims=" %%L in ("%BRANCH_STATE_FILE%") do (
  set "BRANCH_LINE=%%L"
  if "!BRANCH_LINE:~0,2!"=="* " set "CURRENT_BRANCH=!BRANCH_LINE:~2!"
)
del "%BRANCH_STATE_FILE%" >nul 2>nul
if defined CURRENT_BRANCH (
  echo !CURRENT_BRANCH!
) else (
  echo (detached or unknown)
)
echo.
echo Local branches:
git -c safe.directory="%SAFE_DIR%" branch
echo.
echo All branches:
git -c safe.directory="%SAFE_DIR%" branch -a
echo.
echo Current preset scope:
echo %SKILL_SCOPE%
pause
goto menu

:branch_menu
set "CURRENT_BRANCH="
set "BRANCH_STATE_FILE=%TEMP%\tinix_branch_state.txt"
git -c safe.directory="%SAFE_DIR%" branch > "%BRANCH_STATE_FILE%"
for /f "usebackq delims=" %%L in ("%BRANCH_STATE_FILE%") do (
  set "BRANCH_LINE=%%L"
  if "!BRANCH_LINE:~0,2!"=="* " set "CURRENT_BRANCH=!BRANCH_LINE:~2!"
)
del "%BRANCH_STATE_FILE%" >nul 2>nul
  cls
  echo ==========================================
  echo   Branch Manager
  echo ==========================================
  echo   Local branches:
  git -c safe.directory="%SAFE_DIR%" branch
  echo.
    echo   1. Show branches
    echo   2. Checkout branch
    echo   3. Checkout master/main
    echo   4. Merge branch into current
    echo   5. Delete branch
    echo   0. Back
    echo.
    choice /c 123450 /n /m "Choose an option: "
    if errorlevel 6 goto menu
    if errorlevel 5 goto branch_delete
    if errorlevel 4 goto branch_merge
    if errorlevel 3 goto branch_checkout_main
    if errorlevel 2 goto branch_checkout
    if errorlevel 1 goto branch_show
  goto branch_menu

:branch_show
echo.
git -c safe.directory="%SAFE_DIR%" branch
pause
goto branch_menu

:branch_checkout
set "BRANCH_COUNT=0"
set "CHOSEN_BRANCH="
set "BRANCH_LIST_FILE=%TEMP%\tinix_branch_list.txt"
echo.
echo Select branch to checkout:
git -c safe.directory="%SAFE_DIR%" branch > "%BRANCH_LIST_FILE%"
for /f "usebackq delims=" %%B in ("%BRANCH_LIST_FILE%") do (
  set "RAW_BRANCH=%%B"
  if "!RAW_BRANCH:~0,2!"=="* " set "RAW_BRANCH=!RAW_BRANCH:~2!"
  if "!RAW_BRANCH:~0,2!"=="  " set "RAW_BRANCH=!RAW_BRANCH:~2!"
  set /a BRANCH_COUNT+=1
  set "BRANCH_NAME[!BRANCH_COUNT!]=!RAW_BRANCH!"
  echo   !BRANCH_COUNT!. !RAW_BRANCH!
)
del "%BRANCH_LIST_FILE%" >nul 2>nul
if !BRANCH_COUNT! EQU 0 (
  echo No local branches found.
  pause
  goto branch_menu
)
set /p BRANCH_INDEX=Branch number to checkout: 
if not defined BRANCH_INDEX goto branch_menu
for /l %%I in (1,1,!BRANCH_COUNT!) do (
  if "%BRANCH_INDEX%"=="%%I" set "CHOSEN_BRANCH=!BRANCH_NAME[%%I]!"
)
if not defined CHOSEN_BRANCH (
  echo Invalid branch number.
  pause
  goto branch_menu
)
echo.
echo Checking out branch: %CHOSEN_BRANCH%
git -c safe.directory="%SAFE_DIR%" switch "%CHOSEN_BRANCH%"
if errorlevel 1 (
  echo Checkout failed.
  pause
  goto branch_menu
)
echo Checkout succeeded.
pause
goto menu

:branch_checkout_main
git -c safe.directory="%SAFE_DIR%" switch master
if errorlevel 1 git -c safe.directory="%SAFE_DIR%" switch main
if errorlevel 1 (
  echo Could not switch to master/main.
  pause
  goto branch_menu
)
echo Switched to main branch.
pause
goto menu

:branch_merge
set "CURRENT_BRANCH="
set "BRANCH_STATE_FILE=%TEMP%\tinix_branch_state.txt"
git -c safe.directory="%SAFE_DIR%" branch > "%BRANCH_STATE_FILE%"
for /f "usebackq delims=" %%L in ("%BRANCH_STATE_FILE%") do (
  set "BRANCH_LINE=%%L"
  if "!BRANCH_LINE:~0,2!"=="* " set "CURRENT_BRANCH=!BRANCH_LINE:~2!"
)
del "%BRANCH_STATE_FILE%" >nul 2>nul
set "BRANCH_COUNT=0"
set "CHOSEN_BRANCH="
set "BRANCH_LIST_FILE=%TEMP%\tinix_branch_list.txt"
echo.
echo Select branch to merge into current:
git -c safe.directory="%SAFE_DIR%" branch > "%BRANCH_LIST_FILE%"
for /f "usebackq delims=" %%B in ("%BRANCH_LIST_FILE%") do (
  set "RAW_BRANCH=%%B"
  if "!RAW_BRANCH:~0,2!"=="* " set "RAW_BRANCH=!RAW_BRANCH:~2!"
  if "!RAW_BRANCH:~0,2!"=="  " set "RAW_BRANCH=!RAW_BRANCH:~2!"
  set /a BRANCH_COUNT+=1
  set "BRANCH_NAME[!BRANCH_COUNT!]=!RAW_BRANCH!"
  if /I "!RAW_BRANCH!"=="!CURRENT_BRANCH!" (
    echo   !BRANCH_COUNT!. !RAW_BRANCH!  [current]
  ) else (
    echo   !BRANCH_COUNT!. !RAW_BRANCH!
  )
)
del "%BRANCH_LIST_FILE%" >nul 2>nul
if !BRANCH_COUNT! EQU 0 (
  echo No local branches found.
  pause
  goto branch_menu
)
set /p BRANCH_INDEX=Branch number to merge: 
if not defined BRANCH_INDEX goto branch_menu
for /l %%I in (1,1,!BRANCH_COUNT!) do (
  if "%BRANCH_INDEX%"=="%%I" set "CHOSEN_BRANCH=!BRANCH_NAME[%%I]!"
)
if not defined CHOSEN_BRANCH (
  echo Invalid branch number.
  pause
  goto branch_menu
)
if /I "%CHOSEN_BRANCH%"=="%CURRENT_BRANCH%" (
  echo Cannot merge current branch into itself.
  pause
  goto branch_menu
)
echo.
echo Merging branch: %CHOSEN_BRANCH%
git -c safe.directory="%SAFE_DIR%" merge "%CHOSEN_BRANCH%"
if errorlevel 1 (
  echo Merge failed.
  pause
  goto branch_menu
)
  echo Merge succeeded.
  pause
  goto menu

:branch_delete
set "CURRENT_BRANCH="
set "BRANCH_STATE_FILE=%TEMP%\tinix_branch_state.txt"
git -c safe.directory="%SAFE_DIR%" branch > "%BRANCH_STATE_FILE%"
for /f "usebackq delims=" %%L in ("%BRANCH_STATE_FILE%") do (
  set "BRANCH_LINE=%%L"
  if "!BRANCH_LINE:~0,2!"=="* " set "CURRENT_BRANCH=!BRANCH_LINE:~2!"
)
del "%BRANCH_STATE_FILE%" >nul 2>nul
set "BRANCH_COUNT=0"
set "CHOSEN_BRANCH="
set "BRANCH_LIST_FILE=%TEMP%\tinix_branch_list.txt"
echo.
echo Select branch to delete:
git -c safe.directory="%SAFE_DIR%" branch > "%BRANCH_LIST_FILE%"
for /f "usebackq delims=" %%B in ("%BRANCH_LIST_FILE%") do (
  set "RAW_BRANCH=%%B"
  if "!RAW_BRANCH:~0,2!"=="* " set "RAW_BRANCH=!RAW_BRANCH:~2!"
  if "!RAW_BRANCH:~0,2!"=="  " set "RAW_BRANCH=!RAW_BRANCH:~2!"
  set /a BRANCH_COUNT+=1
  set "BRANCH_NAME[!BRANCH_COUNT!]=!RAW_BRANCH!"
  if /I "!RAW_BRANCH!"=="!CURRENT_BRANCH!" (
    echo   !BRANCH_COUNT!. !RAW_BRANCH!  [current]
  ) else (
    echo   !BRANCH_COUNT!. !RAW_BRANCH!
  )
)
del "%BRANCH_LIST_FILE%" >nul 2>nul
if !BRANCH_COUNT! EQU 0 (
  echo No local branches found.
  pause
  goto branch_menu
)
set /p BRANCH_INDEX=Branch number to delete: 
if not defined BRANCH_INDEX goto branch_menu
for /l %%I in (1,1,!BRANCH_COUNT!) do (
  if "%BRANCH_INDEX%"=="%%I" set "CHOSEN_BRANCH=!BRANCH_NAME[%%I]!"
)
if not defined CHOSEN_BRANCH (
  echo Invalid branch number.
  pause
  goto branch_menu
)
if /I "%CHOSEN_BRANCH%"=="%CURRENT_BRANCH%" (
  echo Cannot delete current branch. Switch first.
  pause
  goto branch_menu
)
choice /c AD /n /m "Delete [A]safe (-d) or [D]force (-D)? "
if errorlevel 2 (
  git -c safe.directory="%SAFE_DIR%" branch -D "%CHOSEN_BRANCH%"
) else (
  git -c safe.directory="%SAFE_DIR%" branch -d "%CHOSEN_BRANCH%"
)
if errorlevel 1 (
  echo Delete branch failed.
  pause
  goto branch_menu
)
echo Delete branch succeeded.
pause
goto menu

:remove_skill
set "SKILL_NAME_TO_REMOVE="
set /p SKILL_NAME_TO_REMOVE=Skill key to remove: 
  if not defined SKILL_NAME_TO_REMOVE goto branch_menu
  choice /c YN /n /m "This will delete the skill folder, preset, and matching branch if any. Continue? "
  if errorlevel 2 goto branch_menu

set "SKILL_PATH=%CD%\.agent\skills\%SKILL_NAME_TO_REMOVE%"
set "PRESET_PATH=%PRESET_ROOT%\%SKILL_NAME_TO_REMOVE%"

if exist "%SKILL_PATH%" (
  cmd /c rmdir /s /q "%SKILL_PATH%"
)
  if exist "%PRESET_PATH%" (
    cmd /c rmdir /s /q "%PRESET_PATH%"
  )
  
  set "CURRENT_BRANCH="
  set "BRANCH_STATE_FILE=%TEMP%\tinix_branch_state.txt"
  git -c safe.directory="%SAFE_DIR%" branch > "%BRANCH_STATE_FILE%"
  for /f "usebackq delims=" %%L in ("%BRANCH_STATE_FILE%") do (
    set "BRANCH_LINE=%%L"
    if "!BRANCH_LINE:~0,2!"=="* " set "CURRENT_BRANCH=!BRANCH_LINE:~2!"
  )
  del "%BRANCH_STATE_FILE%" >nul 2>nul
  for /f "delims=" %%B in ('git -c safe.directory="%SAFE_DIR%" branch --list "%SKILL_NAME_TO_REMOVE%"') do (
    if not "%%B"=="" (
      if /I not "%CURRENT_BRANCH%"=="%SKILL_NAME_TO_REMOVE%" (
        git -c safe.directory="%SAFE_DIR%" branch -D "%SKILL_NAME_TO_REMOVE%"
      ) else (
        echo Current branch matches target. Switch branch first, then delete.
    )
  )
)

call :load_presets
echo.
echo Remove skill finished.
pause
goto menu

:new_branch
set "BRANCH="
set /p BRANCH=Branch name: 
if not defined BRANCH goto menu
git -c safe.directory="%SAFE_DIR%" switch -c "%BRANCH%"
pause
goto menu

:checkpoint_commit
set "MSG="
set /p MSG=Commit message: 
if not defined MSG goto menu
choice /c SAC /n /m "Scope: [S]kill preset / [A]ll / [C]ustom? "
if errorlevel 3 goto checkpoint_custom
if errorlevel 2 goto checkpoint_all
goto checkpoint_skill

:checkpoint_skill
git -c safe.directory="%SAFE_DIR%" add %SKILL_SCOPE%
git -c safe.directory="%SAFE_DIR%" commit -m "%MSG%"
pause
goto menu

:checkpoint_all
git -c safe.directory="%SAFE_DIR%" add -A
git -c safe.directory="%SAFE_DIR%" commit -m "%MSG%"
pause
goto menu

:checkpoint_custom
set "PATHS="
set /p PATHS=Paths to add: 
if not defined PATHS goto menu
git -c safe.directory="%SAFE_DIR%" add %PATHS%
git -c safe.directory="%SAFE_DIR%" commit -m "%MSG%"
pause
goto menu

:restore_files
choice /c SK /n /m "Restore: [S]kill preset / [K]checkpoint? "
if errorlevel 2 goto restore_checkpoint
goto restore_skill

:restore_skill
call :restore_scope %SKILL_SCOPE%
if errorlevel 1 (
  echo Restore failed.
  pause
  goto menu
)
echo Restore succeeded.
pause
goto menu

:restore_checkpoint
set "RESTORE_COUNT=0"
set "RESTORE_LOG_FILE=%TEMP%\tinix_restore_log.txt"
git -c safe.directory="%SAFE_DIR%" log --oneline -n 12 -- %SKILL_SCOPE% > "%RESTORE_LOG_FILE%"
echo.
echo Select checkpoint to restore:
for /f "usebackq delims=" %%L in ("%RESTORE_LOG_FILE%") do (
  set /a RESTORE_COUNT+=1
  set "RESTORE_LINE[!RESTORE_COUNT!]=%%L"
  echo   !RESTORE_COUNT!. %%L
)
del "%RESTORE_LOG_FILE%" >nul 2>nul
if !RESTORE_COUNT! EQU 0 (
  echo No checkpoints found for current scope.
  pause
  goto menu
)
set /p RESTORE_INDEX=Checkpoint number to restore: 
if not defined RESTORE_INDEX goto menu
for /l %%I in (1,1,!RESTORE_COUNT!) do (
  if "%RESTORE_INDEX%"=="%%I" set "RESTORE_PICK=!RESTORE_LINE[%%I]!"
)
if not defined RESTORE_PICK (
  echo Invalid checkpoint number.
  pause
  goto menu
)
for /f "tokens=1" %%H in ("!RESTORE_PICK!") do set "RESTORE_COMMIT=%%H"
echo.
echo Restoring scope from checkpoint: !RESTORE_PICK!
git -c safe.directory="%SAFE_DIR%" restore --source "!RESTORE_COMMIT!" --staged --worktree %SKILL_SCOPE%
if errorlevel 1 (
  echo Restore failed.
  pause
  goto menu
)
echo Restore succeeded.
pause
goto menu

  :git_log
set "LOG_SCOPE=%SKILL_SCOPE%"
echo.
echo Checkpoints for current scope:
if defined LOG_SCOPE (
  git -c safe.directory="%SAFE_DIR%" log --oneline -n 12 -- %LOG_SCOPE%
  if errorlevel 1 (
    echo.
    echo Scope-filtered log unavailable, showing latest commits instead:
    git -c safe.directory="%SAFE_DIR%" log --oneline -n 12
  )
) else (
  git -c safe.directory="%SAFE_DIR%" log --oneline -n 12
)
pause
goto menu

:run_app
python main.py
pause
goto menu

:create_skill
cls
echo ==========================================
echo   Create Skill Template
echo ==========================================
set "SKILL_KEY="
set "SKILL_PROFILE=auto"
set /p SKILL_KEY=Skill key (folder name, no spaces): 
if not defined SKILL_KEY goto menu
choice /c ASPTBG /n /m "Profile: [A]uto / [S]can / [P]ost / [T]Auth / [B]ackup / [G]eneral? "
if errorlevel 6 set "SKILL_PROFILE=general"
if errorlevel 5 set "SKILL_PROFILE=backup"
if errorlevel 4 set "SKILL_PROFILE=auth"
if errorlevel 3 set "SKILL_PROFILE=post"
if errorlevel 2 set "SKILL_PROFILE=scan"
if errorlevel 1 if not defined SKILL_PROFILE set "SKILL_PROFILE=auto"
set "FORCE_FLAG="
set "SKILL_DIR=%CD%\.agent\skills\%SKILL_KEY%"
if exist "%SKILL_DIR%" (
  choice /c YN /n /m "Overwrite existing skill if needed? "
  if errorlevel 2 goto menu
  set "FORCE_FLAG=-Force"
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%TOOLS_DIR%create_skill.ps1" -Key "%SKILL_KEY%" -Profile "%SKILL_PROFILE%" %FORCE_FLAG%
if errorlevel 1 (
  echo Create skill failed.
  pause
  goto menu
)
set "AUTO_PRESET_SCOPE=.agent\skills\%SKILL_KEY%"
if not exist "%PRESET_ROOT%" mkdir "%PRESET_ROOT%"
if exist "%PRESET_ROOT%\%SKILL_KEY%" rmdir /s /q "%PRESET_ROOT%\%SKILL_KEY%"
mkdir "%PRESET_ROOT%\%SKILL_KEY%"
> "%PRESET_ROOT%\%SKILL_KEY%\label.txt" echo(%SKILL_NAME%
> "%PRESET_ROOT%\%SKILL_KEY%\scope.txt" echo(%AUTO_PRESET_SCOPE%
set "SKILL_SCOPE=%AUTO_PRESET_SCOPE%"
> "%SCOPE_FILE%" echo(%SKILL_SCOPE%
echo.
echo Skill created:
echo %SKILL_KEY%
echo Auto preset created:
echo %SKILL_KEY%
goto menu

:preset_menu
call :load_presets
:preset_menu_loop
cls
echo ==========================================
echo   Choose Skill Preset
echo ==========================================
if "%PRESET_COUNT%"=="0" (
  echo   (No presets found in %PRESET_ROOT%)
) else (
  for /l %%I in (1,1,%PRESET_COUNT%) do (
    call echo   %%I. %%PRESET_LABEL[%%I]%%
  )
)
echo.
echo   A. Add new preset
echo   R. Rename preset
echo   D. Delete preset
echo   U. Duplicate preset
echo   E. Export preset
echo   I. Import preset
echo   0. Back
echo.
set "PICK="
set /p PICK=Preset number or action: 
if /I "%PICK%"=="A" goto preset_add
if /I "%PICK%"=="R" goto preset_rename
if /I "%PICK%"=="D" goto preset_delete
if /I "%PICK%"=="U" goto preset_duplicate
if /I "%PICK%"=="E" goto preset_export
if /I "%PICK%"=="I" goto preset_import
if "%PICK%"=="0" goto menu

call :resolve_preset "%PICK%"
if not defined RESOLVE_OK (
  echo Invalid preset.
  pause
  goto preset_menu_loop
)
set "SKILL_SCOPE=%RESOLVE_SCOPE%"
> "%SCOPE_FILE%" echo(%SKILL_SCOPE%
echo.
echo Saved preset:
echo %SKILL_SCOPE%
pause
goto menu

:preset_add
cls
echo ==========================================
echo   Add New Preset
echo ==========================================
set "PRESET_KEY="
set "PRESET_LABEL="
set "PRESET_SCOPE="
set /p PRESET_KEY=Preset key (folder name, no spaces): 
if not defined PRESET_KEY goto preset_menu
set /p PRESET_LABEL=Preset label: 
if not defined PRESET_LABEL goto preset_menu
set /p PRESET_SCOPE=Scope paths: 
if not defined PRESET_SCOPE goto preset_menu

if not exist "%PRESET_ROOT%" mkdir "%PRESET_ROOT%"
if exist "%PRESET_ROOT%\%PRESET_KEY%" (
  choice /c YN /n /m "Preset exists. Overwrite files? "
  if errorlevel 2 goto preset_menu
) else (
  mkdir "%PRESET_ROOT%\%PRESET_KEY%"
)

> "%PRESET_ROOT%\%PRESET_KEY%\label.txt" echo(%PRESET_LABEL%
> "%PRESET_ROOT%\%PRESET_KEY%\scope.txt" echo(%PRESET_SCOPE%
call :load_presets
set "SKILL_SCOPE=%PRESET_SCOPE%"
> "%SCOPE_FILE%" echo(%SKILL_SCOPE%
echo.
echo Preset created:
echo %PRESET_KEY%
echo %PRESET_LABEL%
echo %SKILL_SCOPE%
pause
goto menu

:preset_rename
call :load_presets
call :pick_preset "rename" RESOLVE_OK
if not defined RESOLVE_OK goto preset_menu_loop
set "NEW_KEY="
set "NEW_LABEL="
set /p NEW_KEY=New preset key (no spaces): 
if not defined NEW_KEY goto preset_menu
set /p NEW_LABEL=New preset label (Enter to keep current): 
if not defined NEW_LABEL set "NEW_LABEL=%RESOLVE_LABEL%"

if /I "%NEW_KEY%"=="%RESOLVE_KEY%" (
  set "TARGET_DIR=%RESOLVE_DIR%"
) else (
  if exist "%PRESET_ROOT%\%NEW_KEY%" (
    choice /c YN /n /m "Target preset already exists. Overwrite it? "
    if errorlevel 2 goto preset_menu
    rmdir /s /q "%PRESET_ROOT%\%NEW_KEY%"
  )
  ren "%RESOLVE_DIR%" "%NEW_KEY%"
  set "TARGET_DIR=%PRESET_ROOT%\%NEW_KEY%"
)

> "%TARGET_DIR%\label.txt" echo(%NEW_LABEL%
> "%TARGET_DIR%\scope.txt" echo(%RESOLVE_SCOPE%
call :load_presets
set "SKILL_SCOPE=%RESOLVE_SCOPE%"
> "%SCOPE_FILE%" echo(%SKILL_SCOPE%
echo.
echo Preset renamed:
echo %NEW_KEY%
echo %NEW_LABEL%
pause
goto menu

:preset_delete
call :load_presets
call :pick_preset "delete" RESOLVE_OK
if not defined RESOLVE_OK goto preset_menu_loop
choice /c YN /n /m "Delete this preset? "
if errorlevel 2 goto preset_menu
rmdir /s /q "%RESOLVE_DIR%"
call :load_presets
echo.
echo Preset deleted.
pause
goto menu

:preset_duplicate
call :load_presets
call :pick_preset "duplicate" RESOLVE_OK
if not defined RESOLVE_OK goto preset_menu_loop
set "NEW_KEY="
set "NEW_LABEL="
set /p NEW_KEY=New preset key (no spaces): 
if not defined NEW_KEY goto preset_menu
set /p NEW_LABEL=New preset label (Enter to keep current): 
if not defined NEW_LABEL set "NEW_LABEL=%RESOLVE_LABEL%"

if exist "%PRESET_ROOT%\%NEW_KEY%" (
  choice /c YN /n /m "Target preset exists. Overwrite it? "
  if errorlevel 2 goto preset_menu
  rmdir /s /q "%PRESET_ROOT%\%NEW_KEY%"
)
mkdir "%PRESET_ROOT%\%NEW_KEY%"
> "%PRESET_ROOT%\%NEW_KEY%\label.txt" echo(%NEW_LABEL%
> "%PRESET_ROOT%\%NEW_KEY%\scope.txt" echo(%RESOLVE_SCOPE%
call :load_presets
echo.
echo Preset duplicated.
pause
goto menu

:preset_export
call :load_presets
call :pick_preset "export" RESOLVE_OK
if not defined RESOLVE_OK goto preset_menu_loop
set "EXPORT_PATH="
set /p EXPORT_PATH=Export file path (Enter for default): 
if not defined EXPORT_PATH set "EXPORT_PATH=%EXPORT_ROOT%\%RESOLVE_KEY%.json"
for %%P in ("%EXPORT_PATH%") do set "EXPORT_DIR=%%~dpP"
if not exist "%EXPORT_DIR%" mkdir "%EXPORT_DIR%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%TOOLS_DIR%preset_io.ps1" export -OutFile "%EXPORT_PATH%" -Key "%RESOLVE_KEY%" -Label "%RESOLVE_LABEL%" -Scope "%RESOLVE_SCOPE%"
if errorlevel 1 (
  echo Export failed.
  pause
  goto menu
)
echo.
echo Exported to:
echo %EXPORT_PATH%
pause
goto menu

:preset_import
set "IMPORT_PATH="
set /p IMPORT_PATH=Import file path: 
if not defined IMPORT_PATH goto preset_menu
if not exist "%IMPORT_PATH%" (
  echo File not found.
  pause
  goto preset_menu
)
set "IMPORT_FORCE="
choice /c YN /n /m "Overwrite existing preset if needed? "
if not errorlevel 2 set "IMPORT_FORCE=-Force"
powershell -NoProfile -ExecutionPolicy Bypass -File "%TOOLS_DIR%preset_io.ps1" import -InFile "%IMPORT_PATH%" -PresetRoot "%PRESET_ROOT%" %IMPORT_FORCE% > "%TOOLS_DIR%preset_import.tmp"
if errorlevel 1 (
  echo Import failed.
  del /q "%TOOLS_DIR%preset_import.tmp" >nul 2>nul
  pause
  goto menu
)
set "IMPORT_KEY="
set "IMPORT_LABEL="
set "IMPORT_SCOPE="
for /f "usebackq tokens=1,* delims==" %%A in ("%TOOLS_DIR%preset_import.tmp") do (
  if /I "%%A"=="key" set "IMPORT_KEY=%%B"
  if /I "%%A"=="label" set "IMPORT_LABEL=%%B"
  if /I "%%A"=="scope" set "IMPORT_SCOPE=%%B"
)
del /q "%TOOLS_DIR%preset_import.tmp" >nul 2>nul
call :load_presets
set "PRESET_KEY=%IMPORT_KEY%"
if defined IMPORT_SCOPE (
  set "SKILL_SCOPE=%IMPORT_SCOPE%"
  > "%SCOPE_FILE%" echo(%SKILL_SCOPE%
)
echo.
echo Preset imported:
echo %IMPORT_KEY%
echo %IMPORT_LABEL%
echo %SKILL_SCOPE%
pause
goto menu

:pick_preset
set "ACTION=%~1"
set "RESOLVE_OK="
set "RESOLVE_INDEX="
set "RESOLVE_KEY="
set "RESOLVE_LABEL="
set "RESOLVE_SCOPE="
set "RESOLVE_DIR="
set /p RESOLVE_INDEX=Preset number to %ACTION%: 
if not defined RESOLVE_INDEX exit /b 0
call :resolve_preset "%RESOLVE_INDEX%"
exit /b 0

:resolve_preset
set "RESOLVE_OK="
set "RESOLVE_INDEX=%~1"
set "RESOLVE_KEY="
set "RESOLVE_LABEL="
set "RESOLVE_SCOPE="
set "RESOLVE_DIR="
for /l %%I in (1,1,%PRESET_COUNT%) do (
  if "%RESOLVE_INDEX%"=="%%I" (
    set "RESOLVE_OK=1"
    set "RESOLVE_KEY=!PRESET_KEY[%%I]!"
    set "RESOLVE_LABEL=!PRESET_LABEL[%%I]!"
    set "RESOLVE_SCOPE=!PRESET_SCOPE[%%I]!"
    set "RESOLVE_DIR=!PRESET_DIR[%%I]!"
  )
)
exit /b 0

:load_presets
set "PRESET_COUNT=0"
if not exist "%PRESET_ROOT%" exit /b 0
for /f "delims=" %%D in ('dir /b /ad "%PRESET_ROOT%" 2^>nul') do (
  set /a PRESET_COUNT+=1
  set "PRESET_KEY[!PRESET_COUNT!]=%%D"
  set "PRESET_DIR[!PRESET_COUNT!]=%PRESET_ROOT%\%%D"
  set "PRESET_LABEL[!PRESET_COUNT!]=%%D"
  if exist "%PRESET_ROOT%\%%D\label.txt" (
    set /p PRESET_LABEL[!PRESET_COUNT!]=<"%PRESET_ROOT%\%%D\label.txt"
  )
  set "PRESET_SCOPE[!PRESET_COUNT!]="
  if exist "%PRESET_ROOT%\%%D\scope.txt" (
    set /p PRESET_SCOPE[!PRESET_COUNT!]=<"%PRESET_ROOT%\%%D\scope.txt"
  )
)
exit /b 0
