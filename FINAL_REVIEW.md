# Final Production Review

> **Đóng checklist kỹ thuật 2026-10-03 — v1.21.44:** đã nối nút Cài đặt, kiểm tra modal/health/onboarding, verify backup thật và chuẩn bị artifact source/checksum trong thư mục local có ACL giới hạn. Quality gate 235 test + 10 subtest/coverage81%, Build.bat và server restart đạt. Checklist vẫn còn mục tổ chức: người chịu trách nhiệm rollback chưa được chỉ định; chưa công bố release. Xem `docs/RELEASE_CHECKLIST.md` để phân biệt kiểm tra thực tế, controlled tests và giới hạn.

> **Cập nhật 2026-10-03 — v1.21.43:** F6 đã được sửa; nghiệm thu quét → tự tải Facebook thật bằng account #9 **PASS**. Quality gate **235 test + 10 subtest**, coverage **81%**, Build.bat và restart server đạt. Các FAIL/NOT READY bên dưới là bằng chứng tại các snapshot trước sửa; xem kết quả khắc phục F6 ở cuối báo cáo.

> **Cập nhật sau cải tiến — 2026-10-02, v1.21.42:** F1–F5 đã được sửa và đạt kiểm thử hồi quy; quality gate, `Build.bat` và startup/UI của server local đạt. Tải thử Facebook thật bằng account có sẵn được người dùng cho phép đã **PASS**, hai ảnh mới được verify và phục vụ đúng qua API preview. Các phần audit bên dưới giữ nguyên bằng chứng của **snapshot trước sửa v1.21.41**. Xem [Kết quả khắc phục](#kết-quả-khắc-phục--v12142) và nghiệm thu bổ sung ở cuối báo cáo; không coi một bài tải thử là đã nghiệm thu mọi workflow.

## STATUS

**NOT READY** — 4 issue **MUST FIX BEFORE RELEASE**, 1 issue **SHOULD FIX BEFORE RELEASE**.

Review ngày **2026-10-02**, giờ Việt Nam/UTC+7, trên working tree hiện tại của Tinix-Facebook-Hunter **v1.21.41**, SQLite schema **v14**, HEAD **c580d254**.

Quality gate và build kiểm tra đều đạt, nhưng các thử nghiệm failure/recovery tái hiện được mất media ngoài phạm vi xóa, bỏ sót bài sau lỗi ghi DB, nhận video tải dở là hoàn tất và chọn nhầm tiến trình để terminate. Đây là lỗi chức năng/an toàn thực tế, không phải góp ý refactor hoặc polish.

**Không sửa source, schema, dependency, cấu hình vận hành hoặc launcher. Không tạo Git commit.** Chỉ tạo báo cáo này. Không đăng nhập, tải/quét/đăng bài Facebook thật; không chạy migration, cleanup hay restore trên dữ liệu thật.

## BASELINE

### Repository và thay đổi có sẵn

Khi bắt đầu, `git status --short` có **13 file modified**, không có file untracked:

- `core/data_cleanup.py`, `core/db_storage.py`, `core/downloader.py`, `core/media_downloader.py`, `core/page_scraper.py`, `core/url_handler.py`, `core/version.py`.
- `tests/test_flat_storage.py`, `tests/test_p0_hardening.py`.
- `web/routes/downloader.py`, `web/routes/scraper.py`, `web/routes/spy.py`, `web/static/app.js`.

Diff ban đầu: **1.376 dòng thêm, 189 dòng xóa**. Review bao gồm các thay đổi này; không revert hoặc sửa chúng. Cuối review, các file đó vẫn có cùng thống kê diff.

Trong lúc review, 7 tài liệu untracked xuất hiện từ ngoài lượt audit này: `ARCHITECTURE.md`, `DEVELOPMENT_WORKFLOW.md`, `PLAN.md`, `PROJECT_STATUS.md`, `RESEARCH.md`, `RESEARCH_COMPARISON.md`, `UX_UI.md`. Chúng được giữ nguyên. Việc xuất hiện tài liệu không làm thay đổi baseline code đã kiểm thử.

### Tài liệu và implementation

Đã đọc `Agents.md`, `DEVELOPMENT_WORKFLOW.md`, `DesktopBuild.md`, `README.md`, `docs/OPERATIONS.md`, `docs/RELEASE_CHECKLIST.md`, `docs/IMPROVEMENT_AUDIT.md`, `docs/TINIX_PROFILE_BUNDLE.md`, `PLAN.md`, `ARCHITECTURE.md`, `PROJECT_STATUS.md`, `RESEARCH.md` và `RESEARCH_COMPARISON.md`.

- `DEVELOPMENT_WORKFLOW.md` là standard chung; Project Runtime Profile vẫn `TBD`. `PLAN.md`, `ARCHITECTURE.md`, `PROJECT_STATUS.md` và hai tài liệu research cũng là template chưa có dữ liệu project. Không có kế hoạch triển khai/acceptance cụ thể được điền để đối chiếu.
- Không tìm thấy `RELEASE_WORKFLOW.md`; dùng `DesktopBuild.md` và `docs/RELEASE_CHECKLIST.md` làm tài liệu build/phát hành thực tế.
- `docs/IMPROVEMENT_AUDIT.md` ghi schema v13, 150 test, coverage 78% tại ngày 2026-09-14. Hiện tại implementation là v14 và kết quả audit là 198 test, coverage 79%; tài liệu cũ là snapshot lịch sử, không chứng minh trạng thái hiện tại.
- `docs/OPERATIONS.md` nói media còn được bài khác tham chiếu được giữ lại. **Không đúng với flat storage**, xem F1.
- README/operations mô tả cursor chỉ cập nhật sau quét thành công. **Ghi bài thất bại vẫn có thể cập nhật cursor thành công**, xem F2.
- Operations hướng dẫn restore khi DB corrupt. **Restore hiện tại yêu cầu DB đích còn đọc được**, xem F5.
- Operations nhắc `Start Tinix FB Studio.bat`; launcher hiện có là `START.bat`/`START.vbs`.
- README/checklist hướng dẫn mở Cài đặt để migration secrets. Browser acceptance xác nhận không có phần tử `#btn-settings-modal` trong HTML hiện tại, dù JS còn handler tùy chọn. Luồng qua modal đó chưa nghiệm thu được; API config/DPAPI được kiểm thử độc lập. Đây là khoảng lệch tài liệu/UI, không tự nâng thành một finding security chưa có bằng chứng khai thác.

### Môi trường và isolation

Windows, Python **3.11.9**, Node **24.18.0**. Không tìm thấy backend của project đang chạy hoặc listener 7866 ở baseline.

Unit/integration dùng storage tạm. Thử nghiệm bổ sung dùng DB/media/config/Chrome headless cô lập dưới:

`C:\Users\Admin\AppData\Local\Temp\tinix-final-review-09260cb0fa9041de8572fb7fbfc39976`

Evidence tạm: `audit.py`, `results.json`, `rename.json`, `acceptance.py`, `acceptance.json`, `build.log`, `logs/`, `acceptance/server.log`. Báo cáo này ghi lại kết quả cốt lõi để không phụ thuộc vào tuổi thọ thư mục TEMP.

Không terminate tiến trình thật của project khác. F4 được tái hiện bằng mock process inventory và mock hàm terminate. Chỉ backend acceptance do audit tự tạo mới bị terminate để mô phỏng crash; đã dọn cả hai instance sau nghiệm thu.

## TEST / BUILD RESULTS

| Kiểm tra | Kết quả | Bằng chứng / giới hạn |
|---|---|---|
| `./scripts/quality.ps1` | **PASS**, exit 0 | Toàn bộ quality gate thực tế của project |
| `python -m pip check` | **PASS** | No broken requirements found |
| Ruff theo scope quality script | **PASS** | All checks passed |
| mypy theo scope quality script | **PASS** | 6 source files, không có issue |
| pytest qua coverage | **PASS** | **198 passed, 10 subtests passed**, 103,59 giây; không có test fail/skip được báo |
| Branch coverage theo gate | **PASS** | **79%**, ngưỡng 75%; chỉ các module được cấu hình trong `pyproject.toml`, không phải coverage toàn project |
| `node --check web/static/app.js` | **PASS** | JS syntax đạt |
| `python scripts/build_app.py --no-bump` | **PASS**, exit 0 | Builder thực tế; giữ v1.21.41, kiểm tra syntax, tạo shortcut trong Desktop tạm |
| `python -m compileall -q core web utils scripts main.py start_webui.py` | **PASS**, exit 0 | Mở rộng kiểm tra syntax các module Python |
| Wrapper `Build.bat --no-bump` | **NOT TESTED** | Gọi `STOP.bat` → cleanup chọn tiến trình theo port, lỗi F4. Không chạy hành động terminate chưa kiểm tra ownership trên máy thật |
| Installer / release artifact | **N/A** | Builder không tạo EXE/MSI/archive; không có packaging/updater pipeline trong project đã kiểm tra |
| Browser smoke có sẵn | **PASS** | Chrome headless thật, WebUI/WebSocket, tài khoản/secret controls, pause/resume và phục hồi session; thao tác download/preflight được mock |
| Browser/API acceptance bổ sung | **PASS** | Bốn tab, không pageerror/HTTP error, tạo account giả, secret redaction, health, restart process thật cô lập |
| Failure injection bổ sung | **FAIL theo expected invariant** | F1–F5 được tái hiện; không thêm hoặc sửa test source |

**Phân loại baseline:** không có automated failure hoặc flaky test quan sát được trong lượt chạy này. Các failure bổ sung là lỗi hiện tại trên dữ liệu/tiến trình giả lập. Những code pattern gây lỗi cũng đã có trong HEAD; không có bằng chứng để gọi đây là regression mới của 13 file chưa commit. Không chạy lại toàn bộ suite trên HEAD riêng để khẳng định mọi đường tái hiện trước đây giống hệt working tree.

## CRITICAL FINDINGS

### F1 — Xóa một bài/Page có thể xóa media của bài còn giữ lại

**Severity:** CRITICAL  
**Release decision:** **MUST FIX BEFORE RELEASE**

**Problem:** Flat storage lưu đường dẫn root trong `posts.download_path`, còn các file là `<post_id>_1.jpeg`, `<post_id>.mp4`, `<post_id>.txt`. Khi xóa, code liệt kê file cụ thể rồi tìm bài còn tham chiếu bằng `download_path = đường_dẫn_file`. Các bài dùng chung root không khớp điều kiện này, nên media vẫn bị xóa.

**Evidence:**

- `core/db_storage.py:2833`, đặc biệt điều kiện tham chiếu tại **2894**, trong `bulk_delete_post_rows()`.
- `core/data_cleanup.py:60`, đặc biệt query `download_path IN (...)` tại **123**, trong `_delete_scraped_records()`.
- `core/db_storage.py:152`: uniqueness là `(page_name, post_id)`, cho phép cùng story có nhiều dòng. Tái quét cùng Page sau khi đổi tên bằng `save_posts()` thực tế tạo hai dòng cho cùng post ID, nên đây không chỉ là fixture DB bất khả thi.
- `web/routes/spy.py:329` và **360** gọi các đường xóa này; `delete_downloaded_media()` thực sự unlink file ở `core/data_cleanup.py:157`.

**User impact:** Xóa bài cũ hoặc cleanup một Page làm mất ảnh/video/caption của dòng còn giữ lại. Dòng còn lại vẫn báo `downloaded=1`. Backup SQLite của cleanup không chứa media; xóa lẻ còn không có backup DB tự động ở đường này.

**Reproduction:**

1. Tải một story vào flat storage và có hai dòng cùng post ID, chẳng hạn quét lại cùng Page sau đổi tên.
2. Cả hai dòng có `download_path = output_root`.
3. Xóa một dòng với `delete_media=true`; hoặc cleanup một Page trong fixture hai Page dùng chung media.
4. Kết quả thực đo: **còn 1 dòng, `downloaded=1`, nhưng file media và caption đã bị xóa**. Scenario đổi tên cùng URL: **2 dòng trước xóa → 1 dòng sau xóa, media không còn**.

**Recommended fix:** Trước khi unlink, kiểm tra tham chiếu theo danh tính media/post ID và đường dẫn canonical, bao gồm bài còn lại dùng flat root. Dùng chung cơ chế bảo vệ cho xóa lẻ và cleanup; giữ media nếu vẫn có bất kỳ bài được giữ lại tham chiếu. Không cần thay schema hoặc refactor rộng để sửa điều kiện bảo vệ.

## HIGH FINDINGS

### F2 — Lỗi ghi DB vẫn báo lưu thành công và đẩy cursor vượt qua bài chưa lưu

**Severity:** HIGH  
**Release decision:** **MUST FIX BEFORE RELEASE**

**Problem:** `save_posts()` tăng biến `saved` trước khi commit, bắt exception rồi chỉ log và trả số đã tăng. Transaction thất bại bị rollback khi đóng connection, nhưng worker favorite vẫn coi lần quét là thành công và lưu cursor mới.

**Evidence:**

- `core/db_storage.py:1290`, commit tại **1446**, exception bị nuốt tại **1449**, trả `saved` tại **1453**.
- `web/routes/scraper.py:848` nhận số lưu; **893–897** lưu trạng thái `Thành công` và cursor với `successful=True`.
- Luồng quét bài cũ cũng có cập nhật archive cursor tại `web/routes/scraper.py:870` dù kết quả persistence không được xác nhận độc lập.

**User impact:** Khi disk/database write lỗi, UI/lịch sử báo đã lưu nhưng DB không có bài. Lần quét tiếp theo gặp cursor mới và có thể dừng trước những bài đã bị mất; cần reset cursor/quét lại thủ công để khôi phục.

**Reproduction:** Chạy worker favorite thực tế với hai bài giả và SQLite trigger gây `RAISE(ABORT, 'simulated disk write failure')` ở bài thứ hai. Chỉ scraper/provider được fake; `save_posts()` và worker/persistence dùng implementation thật.

Kết quả:

```text
worker_reported_saved = 1
actual_posts = 0
last_status = Thành công
cursor_post_ids = [111111111111111, 222222222222222]
```

**Recommended fix:** Truyền lỗi ghi DB về worker; số lưu chỉ phản ánh transaction đã commit. Không đánh dấu thành công hoặc cập nhật cursor khi persistence fail. Nếu crash xảy ra giữa commit bài và commit cursor, giữ cursor cũ để retry an toàn; không được có trường hợp cursor mới trỏ tới bài chưa commit.

### F3 — File video tải dở được nhận là hoàn tất sau retry/restart

**Severity:** HIGH  
**Release decision:** **MUST FIX BEFORE RELEASE**

**Problem:** Direct download ghi vào tên file cuối cùng ngay từ đầu. Nếu stream lỗi, hàm trả `False` nhưng file dở vẫn tồn tại. Sync chỉ dựa vào extension/count; downloader phát hiện file có sẵn cũng không kiểm tra trạng thái hoàn tất của file.

**Evidence:**

- `core/media_downloader.py:156`: `download_video_direct()` ghi trực tiếp tại **202**; exception ở **237/241** không loại hoặc đổi tên file dở. `download_image()` có cùng dạng ghi tại **123**.
- `core/downloader.py:1781`: cleanup failed bỏ qua khi có media ở **1783**.
- `core/db_storage.py:2624`: sync nhận file từ folder, nhánh tại **2740** đánh dấu `downloaded` khi có video/đủ file.
- `core/downloader.py:1726`: `_handle_existing_post()` mặc định trả `cancel` khi media count đủ, bỏ qua tải lại.
- Startup gọi sync trong `web/app.py`; mở Kho Bài Viết cũng gọi sync ở `web/routes/spy.py:187`.

**User impact:** Mất mạng hoặc mất điện giữa lúc tải có thể để lại video corrupt nhưng UI báo `Đã tải`. Retry bỏ qua file này; không đảm bảo dữ liệu người dùng nhận là media hoàn chỉnh.

**Reproduction:** Fake stream trả 131.072 byte đầu trong response 200.000 byte rồi phát sinh `httpx.ReadError`. Dùng downloader và sync thật trên DB/media tạm.

```text
stream_success = false
partial_file_exists = true
partial_size = 131072
DB after sync = downloaded=1, download_status=downloaded
retry_action = cancel
```

**Recommended fix:** Download vào file tạm không được scanner nhận diện; chỉ rename sang tên cuối sau khi stream hoàn tất và kiểm tra kích thước/tính hợp lệ. Dọn hoặc giữ riêng file tạm khi lỗi; scanner/retry phải phân biệt file chưa hoàn tất. Áp dụng cùng nguyên tắc cho ảnh và direct video.

### F4 — STOP/Build/START có thể terminate server của project khác

**Severity:** HIGH  
**Release decision:** **MUST FIX BEFORE RELEASE**

**Problem:** Cleanup đưa mọi listener trên port 7866 vào danh sách terminate trước khi kiểm tra ownership. Nhánh kiểm tra working directory/command line sau đó không lọc lại danh sách chọn theo port.

**Evidence:**

- `utils/process_cleanup.py:356–360`: listener khớp port được thêm thẳng qua `psutil.Process(conn.pid)`.
- **372** có kiểm tra ownership cho nhánh duyệt process khác; **380** terminate danh sách gộp.
- `STOP.bat` gọi utility này; `Build.bat` gọi STOP trước builder; START gọi cleanup nếu health URL không trả thành công.
- Trái với user instruction và `DEVELOPMENT_WORKFLOW.md:480`: phải xác minh ownership, không kill ứng dụng không liên quan.

**User impact:** Người dùng đang chạy server khác trên 7866 có thể bị tắt server và các child process khi mở/build/dừng Tinix; công việc của project khác có thể bị gián đoạn hoặc mất tiến độ.

**Reproduction:** Mock một listener PID **77777**, không có process thuộc workspace, và thay hàm terminate bằng capture. `cleanup_previous_sessions()` vẫn chọn **[77777]** để terminate. Không thực sự kill process bên ngoài để kiểm chứng.

**Recommended fix:** Áp dụng xác minh project ownership cho cả process lấy từ port trước khi terminate. Nếu listener không thuộc project, trả lỗi port occupied và giữ nguyên nó. STOP phải phản ánh trạng thái dừng thực tế thay vì luôn báo thành công.

## MEDIUM FINDINGS

### F5 — Restore từ backup tốt thất bại khi DB hiện tại đã corrupt

**Severity:** MEDIUM  
**Release decision:** **SHOULD FIX BEFORE RELEASE**

**Problem:** Restore luôn tạo safety backup qua hàm yêu cầu initialize/đọc DB hiện tại. Khi DB đích corrupt, restore dừng trước khi áp dụng backup đã verify.

**Evidence:** `core/database_maintenance.py:62`, gọi safety backup tại **69**; `create_database_backup()` gọi `initialize_database()` tại **38**. `manage_database.py` không có đường fallback cho DB corrupt. Đây chính là trường hợp recovery mà `docs/OPERATIONS.md` hướng dẫn dùng restore.

**User impact:** Lệnh recovery được tài liệu hóa không cứu được DB corrupt dù người dùng có backup tốt. Có thể phục hồi bằng cách giữ bản corrupt riêng rồi restore vào DB mới, nên chưa phải lỗi không thể khôi phục và không nâng lên CRITICAL.

**Reproduction:** Tạo/verify backup DB v14 tốt; ghi file DB đích tạm bằng bytes không phải SQLite; gọi `restore_database(corrupt, verified_backup)`.

```text
DatabaseError: file is not a database
corrupt_preserved = true
verified backup was not applied
```

**Recommended fix:** Hỗ trợ rõ luồng offline restore khi DB đích không đọc được: giữ nguyên bản corrupt/WAL liên quan ở nơi riêng, verify backup nguồn, phục hồi vào DB mới rồi áp dụng có kiểm tra. Không buộc safety backup bằng SQLite thành công mới cho phép recovery. Tài liệu cần mô tả fallback này.

## REGRESSION RISKS

Các thay đổi chưa commit tập trung vào identity story/attachment URL, source row ID, queue, download status, flat storage và UI. Bộ test hiện tại đã bao phủ các trường hợp hai dòng cùng watch URL, pfbid, URL chưa verify, account pool, row-specific retry và recovery queue.

**Không xác nhận regression mới.** So sánh code HEAD cho thấy các root-cause pattern của F1–F5 đã có: bảo vệ media bằng equality của `download_path`, exception ghi DB bị nuốt/cursor advance, ghi media vào tên cuối, terminate theo port và restore phụ thuộc safety backup của DB hiện tại. Kiểm thử bổ sung chỉ khẳng định working tree hiện tại vẫn lỗi.

Các fix tiếp theo cần giữ những invariant đã test: đúng source row/story ID, không gắn video sang bài khác, FIFO Auto Download, Stop current giữ batch sau, Stop all không hồi sinh batch cancelled, lease profile được trả sau worker/browser shutdown.

## DATA INTEGRITY

| Khu vực | Đánh giá |
|---|---|
| Save bài + cursor | **FAIL — F2**. Cursor chưa phụ thuộc persistence thành công |
| Xóa lẻ / cleanup + filesystem | **FAIL — F1**. Bảo vệ shared flat media không đúng |
| Media giữa chừng / crash / retry | **FAIL — F3**. File cuối chưa chứng minh hoàn tất |
| Queue persistence / claim / cancellation | **PASS theo test hiện có**. Claim dùng `BEGIN IMMEDIATE`, guarded transition chống revive batch đã hủy, recovery batch starting/running về queued |
| Task history / orphaned download | **PASS**. Restart process thật cô lập đánh dấu task `interrupted`, bài orphan `failed` |
| Schema migration | **PASS theo test hiện có**. Có backup trước upgrade, từ chối schema mới hơn, kiểm tra schema mới và data preservation |
| Legacy flat-storage migration | **PASS theo suite** với conflict, nested folder, move failure, locked DB và retry. Không migrate media thật |
| Backup / restore DB còn hợp lệ | **PASS theo suite**. Online Backup API, integrity/schema check, safety backup |
| Restore DB corrupt | **FAIL — F5** |
| Historical data | Rating/group/history và trạng thái tải được lưu SQLite; không sửa dữ liệu thật. Lỗi identity sau đổi tên là điều kiện thực tế góp phần tái hiện F1 |

Backup SQLite không thay thế backup media/profile. Không có kết luận rằng hệ thống chịu được mất điện giữa mọi bước; F1–F3 là các failure boundary đã chứng minh chưa an toàn.

## SECURITY

Không phát hiện thêm vulnerability khai thác được ngoài các finding đã ghi. Không dùng kết quả này như chứng nhận pentest toàn bộ dependency.

- Local API startup/session/Host/Origin được kiểm thử: thiếu session **401**, foreign Host **400**, foreign Origin trên thao tác ghi **403**. Session đổi khi process restart; session cũ **401**.
- Account list/detail không trả password/cookie; reveal là thao tác POST có session. Test kiểm tra validation không echo secret và config không lộ cookie.
- Windows DPAPI round-trip, encrypted config và migration có backup đạt trong suite. Export profile ZIP chứa secret không mã hóa là **known limitation được tài liệu hóa**, không phải phát hiện mới.
- Media allow-list/path validation và ZIP traversal/symlink validation có test; không thử với file/profile riêng tư.
- `git ls-files` không cho thấy `.env`, config, DB, SQLite backup hoặc `Chrome Profiles` được track trong snapshot hiện tại. Không xuất giá trị credential ra báo cáo.
- CDP profile là endpoint nhạy cảm cục bộ; chưa thực hiện exploit kiểm soát Chrome từ website khác. Không nâng flag/khả năng giả định thành finding đã xác minh.
- F1/F4 cần sửa vì phạm vi xóa/terminate vượt quá đối tượng người dùng yêu cầu.

## STABILITY / RECOVERY

Backend acceptance chạy từ source hiện tại trên port loopback tạm. Process **88168** bị terminate để mô phỏng crash, sau đó process **10852** khởi động lại cùng storage tạm. Cả hai health response đạt `ready=true`, version **1.21.41**, schema **14** và mọi check đạt.

Tài khoản giả được giữ sau restart; session cũ bị từ chối; task dở về `interrupted`; bài orphan về `failed`. Browser tải bốn tab/WebSocket không có pageerror hoặc HTTP error. Hai backend đã dừng sau test; không để lại instance audit.

Network failure của media: **FAIL F3**. Write failure: **FAIL F2**. Restore corruption: **FAIL F5**. Port conflict handling của wrapper: **FAIL F4** trong mô phỏng ownership.

Preflight auth expired/checkpoint/rate limit, cooldown, retry, worker startup failure, pause/resume/stop và profile lease có coverage trong test suite bằng controlled doubles. Không chạy các tình huống đó trên Facebook thật hoặc reboot máy người dùng.

**Restart server vận hành không áp dụng:** task chỉ audit và ghi documentation, không thay runtime code/config. Project server không chạy ở baseline; không tự mở production storage để startup migration. Việc restart ở trên là acceptance server cô lập, không phải deployment/apply code mới. Không có tác vụ thật bị gián đoạn bởi review.

## PERFORMANCE

Không có release-blocking performance issue được chứng minh trong lượt review này.

Đã kiểm tra query/search/sort whitelist, indexing flat preview theo batch, background worker, queue/task-history retention và bounded concurrency/retry. Test search xác nhận filter trước resolve local previews.

Query UI có tùy chọn lấy tất cả bài và các thao tác xóa có thể duyệt nhiều file. **Chưa benchmark dataset lớn tương đương workload thật**, chưa profile startup migration hoặc xuất toàn bộ Chrome profiles lớn. Không kết luận mọi workload lớn đều đạt; cũng không biến những đường này thành performance finding chỉ từ phỏng đoán hoặc micro-optimization.

## RELEASE / UPDATE

Builder thực tế đã chạy ở `--no-bump`, không đổi version source. Health và badge UI ở browser acceptance đều khớp **v1.21.41**. `compileall` và quality gate đạt.

`Build.bat` là wrapper dừng server → builder → mở START.vbs, không phải tạo artifact executable. Không có standalone installer, auto-update downloader/apply, signature hoặc rollback deployment pipeline để nghiệm thu; GitHub Actions hiện chạy Windows quality gate, không publish release.

**Không tuyên bố đã chạy `Build.bat` hoặc đã tạo release package.** Wrapper chưa chạy vì F4; có thể hoàn tất builder và runtime acceptance bằng command an toàn mà không trigger terminate server bên ngoài. Sau khi sửa ownership, cần nghiệm thu wrapper START/STOP/Build thực tế.

Schema downgrade bị từ chối để bảo vệ DB; SQLite backup và profile/media preservation vẫn là điều kiện vận hành. Recovery từ DB corrupt cần F5. Checklist internal release yêu cầu scan/download một sandbox Page được phép; bước đó chưa chạy trong task này vì không có sandbox input/account được chỉ định.

## MANUAL ACCEPTANCE

Các scenario dưới đây là browser/API/process thật hoặc mô phỏng failure có giới hạn rõ; không phải tất cả đều là E2E Facebook.

| Scenario | Kết quả | Lý do / bằng chứng |
|---|---|---|
| Startup DB/config/media mới cô lập → API health | **PASS** | ready=true, v1.21.41, schema v14, đủ check |
| UI tải bốn tab + realtime | **PASS** | Chrome headless thật; không pageerror/HTTP error |
| Account create → persisted → list/detail không lộ secrets | **PASS** | API thật, credential giả |
| Secret Show/Hide, preserve unsaved input | **PASS** | Browser smoke có sẵn |
| Thiếu session / foreign Host / foreign Origin | **PASS** | 401 / 400 / 403 |
| Kill backend cô lập → restart → session/data/task recovery | **PASS** | PID đổi, session cũ 401, account còn, task interrupted, orphan failed |
| Save favorite/group/reset cursor và scan có/không auto media | **PASS theo controlled tests** | API/worker test; không truy cập Facebook thật |
| Auto Download FIFO, stop current, stop all, restart claim | **PASS theo controlled tests** | Queue SQLite thật, provider/orchestrator doubles |
| Retry bài lỗi, shared watch URL, pfbid/source-row identity | **PASS theo controlled tests** | Suite flat-storage/P0 |
| Xóa một row/Page khi media còn được row khác dùng | **FAIL** | F1; file bị xóa, row còn báo downloaded |
| Page đổi tên → quét lại → xóa dòng cũ | **FAIL** | F1; same-URL/story fixture qua `save_posts()` thật |
| DB write lỗi giữa batch favorite | **FAIL** | F2; 0 bài persist nhưng cursor thành công |
| Mất mạng giữa video → sync/retry | **FAIL** | F3; partial 131.072 byte được báo downloaded |
| Port 7866 của server khác → cleanup | **FAIL trong mô phỏng** | F4; outsider PID được chọn terminate; không kill thật |
| Restore backup tốt lên DB corrupt | **FAIL** | F5; DatabaseError trước apply backup |
| Restore DB hợp lệ / legacy migration conflict + lock | **PASS theo controlled tests** | Suite có sẵn |
| Mở Cài đặt theo hướng dẫn hiện tại | **NOT TESTED qua UI** | Không có entry `#btn-settings-modal`; API đã test độc lập |
| START/STOP/Build wrapper ở desktop thật | **NOT TESTED** | F4; builder đã chạy riêng an toàn |
| Scan/download một Facebook sandbox thật được phép | **NOT TESTED** | Không có sandbox account/Page chỉ định; không tác động production account |
| Reboot Windows / power loss phần cứng / profile chuyển máy | **NOT TESTED** | Chỉ mô phỏng process crash; portability DPAPI là limitation đã biết |
| Performance dataset lớn / full-profile export lớn | **NOT TESTED** | Không có workload chấp nhận được để đo thực tế |

## MUST FIX BEFORE RELEASE

1. **F1 — CRITICAL:** giữ shared flat media khi xóa lẻ/cleanup.
2. **F2 — HIGH:** persistence fail phải dừng cursor advance và success reporting.
3. **F3 — HIGH:** partial download không được mang tên file cuối hoặc được scanner/retry coi là hoàn tất.
4. **F4 — HIGH:** cleanup/STOP/Build/START chỉ terminate process đã xác minh thuộc project.

**Nên sửa trước release:** F5 — phục hồi DB corrupt từ backup tốt và hướng dẫn recovery tương ứng.

Acceptance tối thiểu sau fix: chạy lại quality gate, bốn scenario failure bắt buộc trên, restore-corrupt scenario và wrapper desktop có ownership đã sửa. Sau đó chạy một scan/download sandbox được phép theo checklist release. Không cần refactor rộng, đổi dependency hoặc thêm feature để đóng các finding này.

## SAFE TO DEFER

Không có finding độc lập nào được thêm chỉ để đủ danh sách SAFE TO DEFER. Naming, formatting, minor duplication, UX polish, template chưa điền và ý tưởng kiến trúc không được tính thành issue release.

Known limitation cần giữ trong hướng dẫn vận hành: DPAPI gắn Windows user/máy; profile ZIP và backup có thể chứa secret; ứng dụng dành cho localhost; không có auto-update/package pipeline. Các giới hạn này không phải finding mới và không tự làm tăng số issue.

## FINAL DECISION

**NOT READY. SAFE TO USE NOW: No.**

Lý do là các workflow dữ liệu chính chưa an toàn trong những tình huống thực tế đã tái hiện, dù automated suite/build/happy-path startup đạt. Chưa đưa vào sử dụng thật trước khi xử lý **F1–F4**; **F5** nên xử lý trước release để recovery được tài liệu hóa thực sự hoạt động.

Đã hoàn thành audit, không triển khai fix. File do task tạo: **`FINAL_REVIEW.md`**. Không tạo Git commit; không restart server dữ liệu thật vì task không thay code/runtime.

### Kết quả khắc phục — v1.21.42

Sau audit, người dùng yêu cầu **“Tiến hành cải tiến”** và tiếp tục thực hiện. Phần này ghi kết quả coding task; các kết luận NOT READY/FAIL phía trên thuộc snapshot trước sửa.

| Finding | Thay đổi | Kiểm chứng sau sửa |
|---|---|---|
| F1 — shared media bị xóa | Lọc file theo post identity và đường dẫn của các row còn lại, gồm flat storage và thư mục legacy/nested. Xóa row chạy trong transaction trước khi chốt danh sách file không còn tham chiếu. | Bài numeric/pfbid dùng chung: xóa một row hoặc một Page vẫn giữ media/caption; xóa row cuối mới xóa file. Legacy parent có file được row khác tham chiếu được giữ. |
| F2 — cursor vượt qua batch chưa persist | `save_posts()` rollback toàn batch và truyền exception về caller thay vì trả số đếm chưa commit. | SQLite trigger làm lỗi insert thứ hai: không persist bài/Page nào; worker quét mới/quét cũ báo Lỗi, giữ cả hai cursor và không tạo download URLs. |
| F3 — tải dở bị nhận là hoàn tất | Ảnh/video direct stream vào file `.part`, kiểm tra kích thước/Content-Length khi áp dụng và atomic replace sau khi hoàn tất. Lỗi không thay file hoàn chỉnh có sẵn. | Network error, thiếu byte, file quá nhỏ và success cho cả ảnh/video, với/không có file đích cũ; scanner không promote file `.part` còn lại sau crash. |
| F4 — terminate sai ownership | Listener chỉ được terminate khi có ownership thuộc workspace. Cleanup CLI trả exit 1 nếu cổng chưa được giải phóng; START/STOP/Build và STOP.vbs không báo thành công giả. | Controlled test và dummy HTTP process thật ngoài workspace giữ cổng 7866: cả STOP.bat, START.bat, Build.bat trả exit 1; process ngoài project còn sống. Helper tự dừng dummy sau test. |
| F5 — không restore được DB corrupt | Inspect SQLite chỉ đọc. Restore corrupt dựng và verify file staging, giữ nguyên DB gốc cùng WAL/SHM/journal rồi cài bản tốt; lỗi cài đặt rollback các file gốc. | Restore backup hợp lệ lên DB corrupt đạt, dữ liệu bài còn; bytes của DB/sidecars gốc được giữ. Mô phỏng lỗi cài đặt khôi phục nguyên file gốc; backup không hợp lệ không thay DB đích. |

**Kiểm tra:** thêm `tests/test_production_recovery.py` với **29 test hồi quy**. `scripts/quality.ps1` exit **0**: **227 passed, 10 subtests passed**, coverage **81%** (ngưỡng 75%); dependency check, Ruff, mypy và JavaScript syntax đều đạt. `git diff --check` đạt.

**Build/apply:** chạy **`Build.bat` thực tế**, exit **0**, nâng **1.21.41 → 1.21.42**, cập nhật desktop shortcut và chạy START.vbs. Project backend đã dừng ở baseline nên không có tác vụ của project bị gián đoạn. Server normal local hiện chạy bằng `pythonw.exe ...\Tinix-Facebook-Hunter\main.py`, PID **28568**, khởi động **20:59:11 UTC+7**, sau thay đổi code/version cuối (**20:59:08**). `/api/system/health`: `ready=true`, version **1.21.42**, schema **14**, mọi check true. Frontend `/static/app.js` khớp bytes source; browser thật mở cả bốn tab và WebSocket, badge đúng phiên bản, không pageerror/HTTP error. Không có frontend build riêng trong project này.

**File thay đổi trong coding task này (13):**

- `core/db_storage.py`, `core/data_cleanup.py`, `core/media_downloader.py`, `core/database_maintenance.py`, `core/version.py`.
- `utils/process_cleanup.py`, `Build.bat`, `START.bat`, `STOP.bat`, `STOP.vbs`.
- `tests/test_production_recovery.py` (mới), `docs/OPERATIONS.md`, `FINAL_REVIEW.md`.

Giữ các thay đổi có sẵn ngoài phạm vi sửa; không đổi schema hoặc dependency, không tạo Git commit.

**Trạng thái sau cải tiến:** đóng F1–F5 trong phạm vi các failure đã tái hiện. Bản local v1.21.42 đã được áp dụng và có thể kiểm thử. **Chưa kết luận đã hoàn tất production release**: còn bước scan/download Facebook sandbox được phép; không tự dùng account/Page sản xuất làm mẫu nghiệm thu. Các giới hạn/performance workload lớn và nghiệm thu chưa chạy trong audit vẫn giữ nguyên. File media tải dở từ phiên bản cũ có tên cuối không được tự động sửa hoặc xóa; nếu có, cần kiểm tra và tải lại có chọn lọc. HTML title hiện vẫn không có version, badge đã khớp version; đây là lệch chuẩn desktop có sẵn, ngoài phạm vi sửa F1–F5.

### Nghiệm thu tải Facebook thật được phép — 2026-10-02

Người dùng tiếp tục và chỉ định: **“Cho phép dùng account có sẵn bất kỳ để tải url bất kỳ”**. Chỉ định này cho phép chọn account/bài hiện có thay cho việc chờ sandbox riêng; không thay đổi phạm vi thành quét hoặc tải hàng loạt.

- Preflight account **#3 — Đỗ Minh Duy** và **#6 — Nguyen Tan** trả `AUTH_EXPIRED`; không bắt đầu tải bằng hai account này. Account **#9 — Huỳnh Công Đạt** trả `READY` và được chọn.
- Tải một bài: `https://www.facebook.com/1331723538964257`, source row **#6686**, một luồng, output bình thường `_DOWNLOAD/_TINIX`. Tác vụ bắt đầu **21:10:09**, kết thúc **21:11:36 UTC+7**, **1/1 thành công, 0 lỗi**, không retry hoặc safety pause.
- Hai file JPEG mới: `1331723538964257_1.jpg` (**429.546 bytes**) và `1331723538964257_2.jpg` (**433.482 bytes**); cả hai **2000 × 2000**, decode đầy đủ bằng Pillow. API preview trả HTTP 200 và nội dung khớp bytes file. Không còn `.part` của bài thử.
- DB/API báo đúng row **#6686**: `downloaded=true`, `download_status=downloaded`. Caption cập nhật từ bài thật. File MP4 cũ cùng ID được giữ; kết quả PASS căn cứ vào hai ảnh vừa tải, không căn cứ vào file cũ.
- Server vẫn **v1.21.42**, health `ready=true`; tác vụ đã kết thúc. Không thay runtime code/config, không chạy lại build hoặc restart cho lần nghiệm thu này. Chỉ cập nhật `FINAL_REVIEW.md`; không tạo Git commit.

**Kết luận bổ sung:** bước tải một bài thật có sự cho phép đã **PASS**. Đã đóng phần còn thiếu về download integration tối thiểu; các workflow scan thật, dataset lớn, reboot và các phần NOT TESTED khác trong audit chưa được nghiệm thu thêm. Đây chưa phải bằng chứng mọi checklist phát hành đều hoàn tất.

### Nghiệm thu quét Page thật — 2026-10-03

Tiếp tục trên cùng Page `https://www.facebook.com/InAnhOnlineGiaReToanQuoc`, account **#9**, một worker, giới hạn một bài, delay cautious. Backend đã dừng ở đầu lượt; khởi động lại backend normal local bằng `pythonw.exe main.py`, PID **64072**, health **v1.21.42 / ready=true**. Không có tác vụ đang chạy trước khi bắt đầu.

- **Tắt tự tải: PASS.** Task **#47** completed, lưu row **#6816**, post **1685163956953545**, loại Video, `scraped_at=2026-10-03 08:15:47`. Downloader không chạy, total_posts=0. Quét một bài không đồng nghĩa một bài mới độc nhất: số đếm `new_posts` hiện là số bài được save/upsert.
- **Bật tự tải: FAIL ở bước bàn giao.** Task quét **#48** completed và save/upsert một bài; task tải phát sinh **#49** failed, **0/1 thành công**, không có video mới được xác minh. Row **#6816** giữ `downloaded=0`, `download_status=failed`; không báo thành công giả.
- Preflight tải báo `BROWSER_START_FAILED`: `connect_over_cdp` không kết nối được `http://localhost:9709`, `ECONNREFUSED ::1:9709`. Sau khi task quét kết thúc, quan sát Chrome PID **26268**, parent backend **64072**, giữ profile account `fb_21` trên cổng **9409**; profile chưa sẵn sàng cho preflight ở cổng khác.
- Khi kiểm tra tiếp, PID **26268** đã tự thoát, không cần terminate. Preflight lại cùng account **#9** trả **READY**. Bằng chứng nghiêng về race/timing đóng Chrome và bàn giao profile; chưa kết luận IPv6 là nguyên nhân duy nhất hoặc chỉ đổi localhost sẽ sửa được.

**Finding F6 — HIGH:** luồng quét → tự tải có thể chạy preflight khi Chrome/profile từ bước quét chưa đóng hoàn toàn. Cần xác minh và chờ profile do worker sở hữu được giải phóng trước khi release lease/start auto download, rồi chạy lại hai chế độ trên. Vùng cần điều tra: `PageScraper.stop()` trong `core/page_scraper.py`, coordinator `_run_quick_parallel()` trong `web/routes/scraper.py`, `BrowserManager.start()` trong `core/facebook_parser.py`. Chưa sửa source cho F6 trong lượt nghiệm thu này; không thêm delay hoặc sửa speculative.

**Trạng thái:** F1–F5 giữ kết quả đã đạt; tải thủ công thật và quét không tự tải đạt. **Chưa sẵn sàng xác nhận luồng tự tải sau quét** do F6. Backend vẫn health ready; các tác vụ thử đã kết thúc. File thay đổi trong lượt này: `FINAL_REVIEW.md`; documentation-only nên không chạy lại Build.bat hoặc restart sau cập nhật báo cáo. Không tạo Git commit.

### Khắc phục F6 và nghiệm thu lại — 2026-10-03, v1.21.43

**F6: FIXED / PASS cho scenario đã tái hiện.** Đóng một Playwright browser kết nối qua CDP có thể chỉ ngắt client, không bảo đảm Chrome thực sự đóng. Chrome launcher cũng có thể thoát trước browser. Thay đổi gửi CDP `Browser.close` cho Chrome do worker mở, chờ process thoát và endpoint CDP đóng trước khi bàn giao. Nếu đóng không thành công, worker quick/favorite báo lỗi, bỏ auto-download URLs của queue và không xử lý Page tiếp theo bằng profile đó. Chrome được scraper tái sử dụng vẫn được giữ nguyên. BrowserManager dùng `127.0.0.1` thay localhost để tránh resolve endpoint sang IPv6 như lỗi đã ghi nhận.

**Files thay đổi trong task F6:** `utils/chrome_profiles.py`, `core/page_scraper.py`, `core/facebook_parser.py`, `web/routes/scraper.py`, `tests/test_chrome_handoff.py` (mới), `core/version.py` (builder), `FINAL_REVIEW.md`. Giữ thay đổi có sẵn; không đổi schema/dependency và không tạo Git commit.

**Verification:** 8 test mới kiểm tra thứ tự đóng, timeout, kill/wait đúng process worker, giữ reused Chrome và ngăn auto download/scan Page tiếp khi shutdown lỗi. Chrome thật với profile tạm được đóng qua PageScraper rồi mở ngay bằng BrowserManager trên cổng khác: PASS, cả hai process thoát. `scripts/quality.ps1` exit 0: **235 passed, 10 subtests passed**, coverage **81%**; dependency check, Ruff, mypy và JavaScript syntax đạt. Có 3 DeprecationWarning escape sequence trong parser đã tồn tại, không làm fail gate. `git diff --check` đạt.

**Build/restart:** `Build.bat` exit 0, **1.21.42 → 1.21.43**, cập nhật shortcut, thay backend PID **64072** bằng **103576**. Process mới chạy đúng absolute project `main.py`, bắt đầu **08:39:52 UTC+7**, sau version/build cuối **08:39:49**. Trước build không có task quét/tải chạy; không gián đoạn task. Health **ready=true**, v1.21.43/schema14, mọi check đạt. Không có frontend bundle riêng; frontend dùng source static và API version mới.

**Facebook integration thực tế:** cùng Page/account **#9**, limit1, cautious, một worker, bật auto media. Task quét **#50** completed, save/upsert row **#6816**, `scraped_at=08:40:35`. Task tải **#51** completed, **1/1 thành công, 0 lỗi**. Row #6816 báo `downloaded=1`, `download_status=downloaded`, error trống. File MP4 mới **1685163956953545.mp4**, **3.169.585 bytes**; ffprobe xác nhận video **360×640**, audio, thời lượng **64,343991 giây**. API preview HTTP200, bytes khớp file; không còn `.part` của bài thử. Không chạy lại các account hết hạn hoặc tải/quét hàng loạt.

**Trạng thái sau sửa:** F1–F6 đã có fix và verification cho các lỗi tái hiện; tải thủ công, quét không tự tải và quét có tự tải đã đạt tích hợp thật trong phạm vi mẫu một bài. Backend v1.21.43 tiếp tục chạy, task thử đã kết thúc. Các phần workload lớn, reboot, full-profile portability và phần NOT TESTED khác chưa được mở rộng nghiệm thu; không coi mẫu này là chứng nhận mọi workload/phát hành.

### Hoàn tất checklist kỹ thuật — 2026-10-03, v1.21.44

- Khôi phục entry **Cài đặt** trong header, sử dụng handler/API hiện có; không đổi config của người dùng. Test Chrome thật mở/đóng modal, cảnh báo khi thiếu Chrome và hướng dẫn về tab Tài khoản khi không có account active. Sửa tên launcher trong operations cho đúng START.vbs/START.bat.
- Quality gate **235 passed + 10 subtests**, coverage **81%**, dependency/Ruff/mypy/JS đạt; test bổ sung hai batch stop-current/stop-all đạt. Crash/restart acceptance mới với DB/config/media tạm đạt: account persist, task interrupted, orphan failed, session cũ401. Không cleanup/restore dữ liệu thật.
- Tạo backup dữ liệu hiện tại bằng CLI rồi verify: **schema14, integrityok, supportedtrue**, 2.031.616bytes. Lưu bản sao `exports/releases/tinix_scraper.db.backup-20261003_085213_115026.sqlite` trong thư mục ACL chỉ Admin/Administrators/SYSTEM; backup riêng, không đưa vào source ZIP.
- `Build.bat` exit0, **v1.21.43 → v1.21.44**. Server PID **103576** được thay bằng **107392**, start **08:56:49 UTC+7**, sau build/version cuối; process đúng absolute project main.py. Health readytrue, mọi check true. Browser trên server mới đạt bốn tab/realtime/Cài đặt, không JS/HTTP errors; static JS khớp source. Không có task bị gián đoạn.
- Artifact: `exports/releases/Tinix-Facebook-Hunter-v1.21.44-source.zip`, manifest/checksum **SHA256SUMS.txt**, bản sao checklist/operations/review và evidence. Source ZIP chứa tracked working-tree files và test/report mới cần thiết, không chứa DB/config/.env/log/media/Chrome profiles/.git. Đây là source snapshot cần runtime/dependency, không phải installer. Không upload hoặc publish.
- File thay đổi lượt checklist: `web/static/index.html`, `tests/test_webui_smoke.py`, `tests/test_p0_hardening.py`, `docs/OPERATIONS.md`, `docs/RELEASE_CHECKLIST.md`, `core/version.py`, `FINAL_REVIEW.md`; artifact nằm trong exports được Git ignore. Không tạo Git commit.

**Còn chờ:** người dùng chỉ định người chịu trách nhiệm rollback theo mục cuối checklist. Không tự gán người phụ trách. Các mục technical có bằng chứng theo phạm vi đã ghi; reboot, benchmark workload lớn và profile chuyển máy không nằm trong checklist nội bộ hiện tại và vẫn chưa thực hiện. Không tuyên bố toàn bộ release đã hoàn tất khi trách nhiệm rollback chưa được xác nhận.
