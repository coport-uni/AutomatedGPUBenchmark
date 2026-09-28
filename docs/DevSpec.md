# gpu-burnin-report 개발사양서

| 항목 | 내용 |
|---|---|
| 문서 버전 | 0.3 |
| 작성일 | 2026-09-28 |
| 대상 레포 | gpu-burnin-report |
| 대상 GPU | NVIDIA 소비자용 GeForce, NVIDIA 서버용 데이터센터 GPU |
| 개발 도구 | Claude Code, CommonClaude 하네스 적용 |

---

## 0. 개발 착수 전 필수 절차

이 절의 절차는 **첫 번째 코드 커밋보다 먼저** 완료해야 합니다. 완료되지 않은 상태에서는 기능 개발을 시작하지 않습니다.

### 0.1 external 폴더와 CommonClaude submodule

```bash
git init gpu-burnin-report
cd gpu-burnin-report
mkdir -p external
git submodule add https://github.com/coport-uni/CommonClaude.git \
    external/CommonClaude
git submodule update --init --recursive
```

| 규칙 | 내용 |
|---|---|
| 위치 | `external/CommonClaude` 고정 |
| 수정 금지 | submodule 내부 파일은 이 레포에서 직접 수정하지 않습니다. 변경이 필요하면 CommonClaude 레포에 별도 PR을 보냅니다 |
| 버전 고정 | submodule은 특정 커밋에 고정하고, 갱신은 `chore(harness): bump CommonClaude` 커밋으로만 합니다 |
| 클론 방법 | 사용자와 개발자 모두 `git clone --recurse-submodules`를 사용합니다 |

사양서 작성 시점에 확인한 CommonClaude 최신 커밋은 `ca42b88`, 2026-09-02입니다.

### 0.2 Claude Code 하네스 적용

CommonClaude가 제공하는 구성요소와 이 레포에서의 적용 방법은 다음과 같습니다.

| CommonClaude 구성요소 | 역할 | 적용 방법 |
|---|---|---|
| `CLAUDE.md` | 전역 규칙 | 루트 `CLAUDE.md` 첫 줄에서 `@external/CommonClaude/CLAUDE.md`로 import |
| `.claude/settings.json` | hook 등록, 환경변수 | 루트 `.claude/settings.json`에 동일 내용을 두되, hook 경로를 submodule로 지정 |
| `.claude/hooks/*.sh` | 규칙 자동 강제 | 복사하지 않고 submodule 경로를 직접 호출 |
| `ToDo.md` 규칙 | 작업 이력 | 루트에 `ToDo.md` 생성, append only |
| `LearnedPatterns.md` 규칙 | 교훈 축적 | 루트에 생성, bootstrap 절차 준수 |
| `claude_test/` 규칙 | 디버그 스크립트 분리 | 루트에 `claude_test/README.md` 생성 |

**루트 CLAUDE.md 구성**

```markdown
@external/CommonClaude/CLAUDE.md

# Project Overrides: gpu-burnin-report

## Scope
- Target: NVIDIA consumer and datacenter GPUs only.

## Hardware verification
- Burn and VRAM tests heat the GPU. Never start them without
  explicit operator confirmation in the session.
...
```

Claude Code 문서 기준으로 CLAUDE.md는 `@path` 문법으로 다른 파일을 import할 수 있고, 상대 경로는 import하는 파일 기준으로 해석되며, 재귀 import는 최대 4단계입니다. submodule은 작업 디렉터리 안에 있으므로 외부 import 승인 절차가 발생하지 않습니다. CommonClaude §1에 따라 프로젝트 수준 규칙이 전역 규칙보다 우선하므로, 이 레포 고유 규칙은 루트 `CLAUDE.md`의 Project Overrides 절에 둡니다.

**루트 .claude/settings.json 구성**

CommonClaude의 hook 명령은 `$CLAUDE_PROJECT_DIR/.claude/hooks/...`를 호출합니다. `CLAUDE_PROJECT_DIR`은 세션이 시작된 프로젝트 루트를 가리키므로, submodule 안의 설정을 그대로 쓰면 경로가 맞지 않습니다. 따라서 루트 설정 파일의 경로만 submodule로 바꿉니다.

```json
{
  "env": {
    "MAX_THINKING_TOKENS": "10000",
    "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE": "50"
  },
  "hooks": {
    "PreToolUse": [
      { "matcher": "Write|Edit", "hooks": [{ "type": "command",
        "command": "bash \"$CLAUDE_PROJECT_DIR\"/external/CommonClaude/.claude/hooks/pre-write-guard.sh",
        "timeout": 10 }] },
      { "matcher": "Bash", "hooks": [{ "type": "command",
        "command": "bash \"$CLAUDE_PROJECT_DIR\"/external/CommonClaude/.claude/hooks/pre-bash-secret-scan.sh",
        "timeout": 10 }] },
      { "matcher": "Read", "hooks": [{ "type": "command",
        "command": "bash \"$CLAUDE_PROJECT_DIR\"/external/CommonClaude/.claude/hooks/pre-read-env-guard.sh",
        "timeout": 10 }] }
    ],
    "PostToolUse": [
      { "matcher": "Write|Edit", "hooks": [
        { "type": "command",
          "command": "bash \"$CLAUDE_PROJECT_DIR\"/external/CommonClaude/.claude/hooks/post-write-lint.sh",
          "timeout": 30 },
        { "type": "command",
          "command": "bash \"$CLAUDE_PROJECT_DIR\"/external/CommonClaude/.claude/hooks/post-write-debug-remind.sh",
          "timeout": 10 } ] }
    ],
    "Stop": [ "CommonClaude settings.json의 Stop prompt hook을 그대로 복사" ]
  }
}
```

위 `Stop` 항목은 설명용 표기입니다. 실제 파일에는 CommonClaude 원본의 prompt hook 객체를 그대로 넣습니다. 적용 작업은 `scripts/setup_harness.sh`로 자동화하고, 스크립트는 다음을 수행합니다.

1. submodule 초기화 여부 확인
2. 루트 `CLAUDE.md`, `.claude/settings.json`, `ToDo.md`, `claude_test/README.md`가 없으면 생성
3. hook 의존 도구 `jq`, `ruff` 설치 여부 확인
4. 필수 MCP 서버 등록 여부를 `claude mcp list`로 확인

**hook이 강제하는 규칙**

| hook | 이벤트 | 동작 |
|---|---|---|
| pre-write-guard.sh | PreToolUse, Write와 Edit | `tests/`에 `debug_`, `scratch_`, `tmp_`, `experiment_`로 시작하는 파일 작성을 차단 |
| pre-bash-secret-scan.sh | PreToolUse, Bash | API key, token, password 리터럴이 포함된 명령을 차단 |
| pre-read-env-guard.sh | PreToolUse, Read | `.env`, `.key`, `.pem` 파일 읽기를 차단 |
| post-write-lint.sh | PostToolUse, Write와 Edit | Python 파일에 `ruff check`, `ruff format --check` 실행 후 오류를 Claude에 전달 |
| post-write-debug-remind.sh | PostToolUse, Write와 Edit | `claude_test/`에 파일 추가 시 README 갱신 요청 |
| Stop prompt hook | Stop | ToDo.md 항목, gh issue, ruff 통과, claude_test README 갱신을 종료 전 확인 |

**필수 MCP 서버**

CommonClaude §7은 Serena, Context7, Fetch를 필수로 지정합니다.

```bash
claude mcp add serena -- \
  uvx --from git+https://github.com/oraios/serena \
  serena start-mcp-server --context ide-assistant --project "$(pwd)"
claude mcp add context7 -- npx -y @upstash/context7-mcp
claude mcp add fetch -- uvx mcp-server-fetch
claude mcp list
```

### 0.3 하네스 적용 완료 확인

아래 항목이 모두 확인되어야 개발 착수로 인정합니다. 확인 결과는 첫 PR의 `## Testing` 절에 실제 출력으로 첨부합니다.

| 번호 | 확인 방법 | 기대 결과 |
|---|---|---|
| 1 | `git submodule status` | `external/CommonClaude` 커밋 해시 출력 |
| 2 | Claude Code에서 `/memory` | 루트 CLAUDE.md와 import된 CommonClaude CLAUDE.md가 함께 표시 |
| 3 | Claude Code에서 `/hooks` | 위 6개 hook 등록 표시 |
| 4 | `tests/debug_x.py` 작성 시도 | pre-write-guard가 차단 |
| 5 | 린트 위반 Python 파일 작성 | post-write-lint가 ruff 오류 반환 |
| 6 | `claude mcp list` | serena, context7, fetch 연결 |

---

## 1. CommonClaude 준수 규칙

CommonClaude 규칙 전체가 적용됩니다. 이 레포에서 특히 영향이 큰 항목만 정리합니다.

### 1.1 작업 절차

모든 작업은 크기와 무관하게 다음 순서를 따릅니다.

| 단계 | 내용 |
|---|---|
| 1 | 명령 입력 검증: 대상, 방법, 목적이 명확한지, 참고 자료가 있는지 확인 |
| 2 | `LearnedPatterns.md`의 관련 항목 확인 |
| 3 | `ToDo.md`에 작업 추가, append only |
| 4 | 사용자 확인 |
| 5 | `gh issue create` |
| 6 | `main`에서 `<type>/<short-description>` 브랜치 생성 |
| 7 | 구현 |
| 8 | 검증, 1.3절 참조 |
| 9 | Conventional Commits 형식으로 커밋 |
| 10 | `gh issue edit`로 진행 상황 갱신 |
| 11 | push 후 `gh pr create`, `## Testing`에 실제 출력 첨부 |
| 12 | 검증 완료 확인 후 merge, 로컬 브랜치 삭제 |

### 1.2 언어와 코드 규칙

| 항목 | 규칙 |
|---|---|
| 언어 | 코드 주석, docstring, 커밋 메시지, README를 포함한 레포 내 문서, GitHub issue, PR은 **영어** |
| 코드 스타일 | MIT CommLab Coding and Comment Style |
| 이름 | 변수, 함수, 상수, 모듈은 `lower_case`, 클래스는 `CamelCase` |
| 줄 길이 | 80 column, 들여쓰기 4 space |
| docstring | 공개 함수와 클래스는 PEP 257, Google style 권장, `Args`, `Returns`, `Raises` 포함 |
| 린트 | Ruff, `pyproject.toml`의 `[tool.ruff]`에 `line-length = 80` |
| 테스트 | magic number 금지, 테스트 입력에 맞춘 hardcoding 금지 |
| 디버그 코드 | `claude_test/`에 두고 `claude_test/README.md`에 행 추가 |
| 버전 | SemVer, 초기 개발은 `0.y.z` |
| PR 크기 | 가능하면 400줄 이하 |

이 사양서는 사용자 검토용 한국어 문서입니다. 레포에 커밋하는 README와 docs 문서는 위 규칙에 따라 영어로 작성합니다.

### 1.3 Verification Gate와 GPU 작업

CommonClaude §5.1은 장치를 구동하는 코드는 **실제 장치에서, 운영자가 입회한 상태로** 실행해야 검증된 것으로 봅니다. 가열을 일으키는 동작은 운영자 확인 없이 시작하지 않도록 규정합니다. GPU 부하 테스트와 VRAM 테스트는 GPU를 가열하므로 이 규칙이 그대로 적용됩니다.

| 변경 유형 | 커밋 전 필요한 검증 |
|---|---|
| runner, telemetry 수집, 중단 처리 등 GPU를 구동하는 코드 | 실제 GPU에서 운영자 입회 하에 실행, 콘솔 출력 보존 |
| 파서, 판정, 그래프, 레포트 생성 | fixture 기반 테스트 통과, `ruff check`, `ruff format --check` 출력 첨부 |
| 문서 | 기술한 명령과 출력이 실제 코드 및 실행 결과와 일치하는지 대조 |

| 규칙 | 내용 |
|---|---|
| 세션 내 확인 | Claude Code는 burn, VRAM 테스트 실행 전 반드시 운영자에게 확인을 받습니다 |
| 개발용 짧은 실행 | 하드웨어 경로 개발 중에는 `quick` 프로필을 사용하고, 900 s 전체 실행은 릴리스 전 검증에서만 수행합니다 |
| CI 범위 | GitHub Actions에는 GPU가 없으므로 CI는 린트, fixture 테스트, 이미지 빌드까지만 수행합니다. CI 통과는 하드웨어 검증을 대체하지 않습니다 |
| 미검증 표기 | GPU 경로를 실행하지 못한 PR은 `## Testing`에 `NOT VERIFIED`를 명시하고 merge하지 않습니다 |

### 1.4 개발 컨테이너와 실행 컨테이너 구분

CommonClaude는 개발 환경을 `--privileged` Docker 컨테이너, Ubuntu 24.04로 정의합니다. 반면 이 제품의 실행 컨테이너는 privileged 없이 동작하도록 설계합니다. 두 컨테이너를 혼동하지 않도록 구분합니다.

| 구분 | 개발 컨테이너 | 실행 컨테이너 |
|---|---|---|
| 목적 | Claude Code로 코드 작성 | 사용자가 테스트 실행 |
| 기준 | CommonClaude 환경 정의 | 이 사양서 4절 |
| 권한 | `--privileged` | 일반 권한, `--gpus`, `--init` |
| Dockerfile | 해당 없음, 연구실 공용 이미지 사용 | 레포 루트 `Dockerfile` |

---

## 2. 제품 개요

### 2.1 목적

컨테이너 하나로 NVIDIA GPU의 15분 부하 및 온도 테스트, VRAM 테스트를 자동 수행하고, 결과를 그래프가 포함된 문서로 저장합니다.

### 2.2 범위

| 포함 | 제외 |
|---|---|
| NVIDIA GeForce 소비자용 GPU | AMD, Intel GPU |
| NVIDIA 데이터센터 GPU | 다중 노드 동시 실행 |
| 단일 호스트 다중 GPU | InfiniBand, NCCL 통신 테스트 |

### 2.3 참고한 기존 도구

| 도구 | 이 레포에서의 역할 |
|---|---|
| wilicc/gpu-burn | 부하 엔진 |
| ComputationalRadiationPhysics/cuda_memtest | 기본 VRAM 엔진 |
| GpuZelenograd/memtest_vulkan | 소비자용 추가 VRAM 검사 옵션 |
| NVIDIA DCGM | 서버용 교차 검증 옵션, 판정 등급 체계 |
| huggingface/gpu-fryer | GPU 간 성능 편차 기준 |
| microsoft/superbenchmark | Monitor 지표 구성, 레포트 구조 참고 |

---

## 3. 레포 구조

```
gpu-burnin-report/
├── README.md                     # 영어, 5절 요건 준수
├── CLAUDE.md                     # @external/CommonClaude/CLAUDE.md + overrides
├── ToDo.md                       # append only
├── LearnedPatterns.md
├── LICENSE
├── pyproject.toml                # ruff line-length = 80
├── Dockerfile
├── compose.yaml
├── .gitmodules
├── .claude/settings.json         # hook 경로는 external/CommonClaude
├── external/
│   └── CommonClaude/             # git submodule
├── scripts/
│   └── setup_harness.sh
├── docker/entrypoint.sh
├── config/
│   ├── default.yaml
│   └── profiles/
│       ├── quick.yaml
│       ├── consumer.yaml
│       └── datacenter.yaml
├── src/gpubench/
│   ├── cli.py                    # run, status, attach, stop, plot, compare, pdf
│   ├── orchestrator.py
│   ├── detect.py                 # GPU 계열 판별, 지원 필드 탐지
│   ├── collectors/
│   │   ├── telemetry.py          # NVML 1 s 샘플링, 미지원 필드는 null
│   │   └── sysinfo.py            # GPU, 드라이버, CPU, 메모리, OS
│   ├── runners/
│   │   ├── base.py
│   │   ├── gpu_burn.py
│   │   ├── cuda_memtest.py
│   │   ├── memtest_vulkan.py     # consumer 옵션
│   │   └── dcgm_diag.py          # datacenter 옵션
│   ├── analysis/
│   │   ├── loader.py
│   │   ├── phases.py
│   │   └── metrics.py
│   ├── evaluate.py
│   ├── charts/
│   │   ├── catalog.py
│   │   ├── static_mpl.py
│   │   ├── interactive_plotly.py
│   │   └── theme.py
│   ├── report/
│   │   ├── docx_builder.py       # python-docx, A4 1장 report.docx
│   │   ├── docx2pdf.py           # LibreOffice UNO, report.pdf
│   │   ├── render.py             # report.md, report.html
│   │   └── templates/
│   ├── console/
│   │   ├── mode.py
│   │   ├── live.py
│   │   └── plain.py
│   └── runtime/
│       ├── lock.py
│       ├── signals.py
│       └── state.py
├── tests/
│   ├── fixtures/
│   │   ├── consumer/
│   │   └── datacenter/
│   └── test_*.py
├── claude_test/
│   └── README.md
├── results/                      # .gitignore
└── .github/workflows/ci.yml
```

---

## 4. 기능 사양

### 4.1 테스트 흐름

| 구간 | 기본 시간 | 수행 내용 |
|---|---|---|
| Preflight | 약 30 s | GPU 인식, 계열 판별, 잔여 프로세스, lock, ECC와 remap 초기값 |
| Idle | 60 s | 무부하 샘플링 |
| Burn warm-up | 300 s | gpu-burn, 판정 집계에서 분리 |
| Burn steady | 600 s | gpu-burn 계속 |
| Cooldown | 120 s | 부하 종료 후 샘플링 |
| VRAM | 600 s | cuda_memtest |
| 옵션 | 300 s 또는 약 15분 | consumer는 memtest_vulkan, datacenter는 `dcgmi diag -r 3` |
| Report | 수 초 | 판정, 그래프, 문서 생성 |

### 4.2 GPU 계열별 차이

| 항목 | consumer | datacenter |
|---|---|---|
| 판별 | nvidia-smi Product Brand가 GeForce | 그 외 데이터센터 브랜드, `--gpu-class`로 override 가능 |
| ECC | 대부분 비활성, 비활성 시 ECC 규칙 N/A | 활성 |
| Row remap | 해당 없음 | 검사 |
| 메모리 온도 | 미지원이면 null | 수집 |
| 팬 속도 | 팬 보고 제품만 | 미보고 제품은 제외 |

### 4.3 수집 지표

`telemetry.jsonl`에 1 s 주기, GPU별 한 줄로 저장합니다.

| 필드 | 단위 |
|---|---|
| `ts`, `phase`, `gpu_index`, `gpu_uuid` | |
| `temp_gpu`, `temp_mem` | °C |
| `power_draw`, `power_limit` | W |
| `clk_sm`, `clk_mem` | MHz |
| `util_gpu`, `mem_used` | %, MiB |
| `fan_speed`, `pstate` | %, 문자열 |
| `clk_event_reasons` | NVML bitmask |
| `ecc_corr`, `ecc_uncorr`, `remap_*` | count |
| `pcie_gen`, `pcie_width` | |

`sysinfo.json`에는 GPU 모델, VBIOS, 드라이버, CUDA, PCIe, ECC 모드, 장치 보고 온도 한계값, CPU 모델과 코어 수, 메모리 용량과 구성, OS와 커널을 저장합니다. CPU와 메모리는 `/proc/cpuinfo`, `/proc/meminfo`, OS는 `uname`과 `/etc/os-release`에서 수집합니다.

### 4.4 판정 기준

**원칙: NVIDIA 공식 문서 또는 사용 도구의 기본값에 근거한 기준만 사용합니다.** 근거가 없는 임계값은 판정에 쓰지 않고 참고값으로만 표시합니다.

**등급 매핑**은 DCGM 오류 심각도를 따릅니다. DCGM 문서는 ISOLATE와 RESET 등급을 즉시 조치 대상으로, 그 외 등급은 현장별 분석 대상으로 설명합니다.

| DCGM 심각도 | 이 도구의 등급 |
|---|---|
| ISOLATE, RESET | FAIL |
| MONITOR | WARN |
| 적용 불가 | N/A |

**판정 규칙**

| 규칙 | 기준 | 이탈 시 | 출처 |
|---|---|---|---|
| 연산 오류 | gpu-burn 결과 OK | FAIL | gpu-burn 자체 판정 |
| VRAM 패턴 오류 | 0건 | FAIL | DCGM memtest, 오류 검출 시 실패 |
| ECC DBE 증가 | 0건 | FAIL | DCGM DBE 오류 = ISOLATE |
| HW Slowdown, HW Thermal, Power Brake | 발생 없음 | WARN | NVML 정의, DCGM clocks event = MONITOR |
| SW Thermal Slowdown | 발생 없음 | WARN | 위와 같음 |
| 최고 온도 | 장치 보고 GPU Slowdown Temp 미만 | WARN | nvidia-smi 보고값, DCGM 온도 위반 = MONITOR |
| GPU 간 성능 | 최고 GPU 대비 90 % 이상 | FAIL | gpu-fryer 기본 tolerance 10 % |

**판정에 쓰지 않는 참고값**: SM 클럭 유지율, Steady 평균 온도, 최대 전력. 결과 표에는 표시하되 등급에 반영하지 않습니다.

**검토 후 채택하지 않은 값**

| 후보 | 사유 |
|---|---|
| DCGM `temperature_max` 기본값 30.0 | 부하 테스트 온도로 비현실적이며 문서 표기 오류 가능성 |
| DCGM `gflops_tolerance_pcnt` 기본값 0.0 | 기본 상태에서 비교 비활성 |
| gpu-fryer의 SW throttling 실패 처리 | DCGM 등급과 충돌, NVIDIA 공식 문서 우선. datacenter 프로필에서 엄격 모드 옵션으로 제공 가능 |

### 4.5 출력물

실행마다 `results/<hostname>_<YYYYMMDD-HHMMSS>/`에 생성합니다.

| 파일 | 형식 | 용도 |
|---|---|---|
| `report.docx` | Word, A4 1장 | 편집 가능한 원본, PDF의 입력 |
| `report.pdf` | A4 1장, `report.docx`에서 변환 | 결재, 공유 |
| `report.html` | 정적 PNG 내장 | 브라우저 열람 |
| `report.md` | PNG 참조 | Git, 위키 |
| `dashboard.html` | Plotly, JS 내장 | 확대, hover 분석, 오프라인 |
| `summary.json` | JSON | 자동화 |
| `telemetry.jsonl`, `sysinfo.json` | 원본 | 재렌더링 |
| `charts/png`, `charts/svg` | 이미지 | 문서 편집 |
| `logs/*.log` | 도구 원본 출력 | 원인 분석 |

### 4.6 A4 1장 PDF 레포트 구성

| 순서 | 영역 | 내용 |
|---|---|---|
| 1 | 머리글 | 제목, 호스트, 실행 시각, 프로필, 총 소요, 최종 판정 |
| 2 | 요약 | 결론 한 문단 |
| 3 | 시스템 정보 | GPU, 드라이버와 CUDA, PCIe, ECC와 냉각, CPU, 메모리, OS와 커널 |
| 4 | 테스트 조건 | 구간별 시간과 도구 옵션, 샘플링, 실행 방식, 도구 버전, 판정 기준 |
| 5 | 측정 그래프 | GPU 코어 온도, 소비 전력, SM 클럭 부하 구간, Throttling 발생 구간 |
| 6 | GPU별 결과 | 온도, 전력, 클럭 유지율, Gflop/s, throttling 시간, 오류 수, 판정 |
| 7 | 판정 근거 | 규칙, 기준, GPU별 측정값과 등급, 기준 출처 |
| 8 | 바닥글 | 도구 버전, 원본 파일 목록, 쪽 번호 |

| 규칙 | 내용 |
|---|---|
| 분량 | A4 세로 1장을 넘지 않습니다. 넘으면 판정 근거 표에 WARN과 FAIL 항목만 남깁니다 |
| 그래프 제목 | 번호가 아닌 측정 항목 이름으로 표기 |
| 그래프 축 | Y축 하나, 구간은 배경색 |
| 판정 표시 | 색상과 아이콘, 글자를 함께 사용 |
| 렌더링 | 4.6.1절 파이프라인을 따릅니다 |
| 샘플 표기 | 가상 데이터로 만든 예시에는 SAMPLE 표시 |

#### 4.6.1 Word 우선 생성 파이프라인

PDF는 직접 만들지 않고, **먼저 Word 파일을 만든 뒤 그 Word 파일을 PDF로 변환**합니다. 사용자는 PDF와 함께 편집 가능한 `report.docx`를 받습니다.

```
telemetry.jsonl ─> analysis ─> charts/png ─┐
sysinfo.json ─────────────────────────────┼─> report.docx ─> report.pdf
evaluate 결과 ────────────────────────────┘   python-docx      LibreOffice UNO
```

| 단계 | 도구 | 사양 |
|---|---|---|
| 1 | matplotlib Agg | 그래프를 300 dpi PNG로 저장. python-docx는 SVG 삽입을 지원하지 않으므로 Word용은 PNG를 사용 |
| 2 | python-docx | A4 세로, 여백 좌우 10 mm, 표는 가로 구분선만 사용, 한글 글꼴은 Noto Sans CJK KR을 ascii, hAnsi, eastAsia에 모두 지정 |
| 3 | 스키마 검증 | 생성한 docx를 OOXML 스키마로 검증, 오류가 있으면 실행 실패 처리 |
| 4 | LibreOffice UNO | headless 상태로 docx를 열어 Asian autospace를 끄고 `writer_pdf_Export`로 출력 |
| 5 | 페이지 검사 | PDF가 1페이지를 넘으면 판정 근거 표를 WARN과 FAIL만 남겨 2단계부터 다시 생성 |
| 재변환 | `gpubench pdf <result_dir>` | 사용자가 `report.docx`를 수정한 뒤 4단계만 다시 실행해 `report.pdf`를 갱신 |

**실행 컨테이너 추가 패키지**: `libreoffice-writer-nogui`, `python3-uno`, `fonts-noto-cjk`. 이미지 크기가 늘어나므로 README Requirements 절에 디스크 요구량을 명시합니다.

**프로토타입에서 확인한 주의사항**. 가상 데이터로 파이프라인을 실제 구현해 1페이지 PDF 출력까지 확인했습니다. 아래 항목은 개발 시작 시 `LearnedPatterns.md` 초기 항목으로 등록합니다.

| 문제 | 원인 | 조치 |
|---|---|---|
| PDF에서 한글과 숫자 사이에 공백이 추가됨, 예: `0 건` | LibreOffice DOCX 가져오기가 `w:autoSpaceDE`, `w:autoSpaceDN`을 반영하지 않음 | `soffice --convert-to` 대신 UNO로 열어 모든 문단 스타일과 문단의 `ParaIsCharacterDistance`를 False로 설정한 뒤 출력 |
| 표 열 너비가 지정값과 다르게 나와 2페이지로 넘어감 | 셀 너비만 지정하고 `tblGrid`와 `tblW`를 지정하지 않음 | `gridCol`, `tblW`, 고정 레이아웃을 함께 지정 |
| docx 스키마 검증 실패 | `tcPr`, `tblPr`, `tblBorders` 하위 요소를 스키마 순서와 다르게 추가함 | 스키마 순서에 맞춰 삽입하는 helper를 사용 |
| 스키마 검증 실패 | python-docx 기본 템플릿의 `w:zoom`에 `w:percent` 누락 | 저장 전에 `w:percent="100"` 지정 |

### 4.7 그래프 구성

| 분류 | 항목 | 적용 |
|---|---|---|
| 시계열 | GPU 코어 온도, 소비 전력, SM 클럭, 사용률과 VRAM 사용량, Throttling 발생 구간, 연산 성능 | 공통 |
| 시계열 | 팬 속도 | consumer, 팬 보고 제품 |
| 시계열 | ECC와 remap 카운터 | datacenter |
| 분석 | 온도 대비 클럭 산점도, 온도 분포, GPU 간 성능, GPU별 최고 온도, VRAM 패턴별 오류, 판정 heatmap | GPU 2개 이상일 때 일부 |
| 비교 | 두 실행의 온도 곡선, 클럭 비교 | `compare` 명령 |

| 도구 | 용도 | 사유 |
|---|---|---|
| matplotlib Agg | PNG, SVG, PDF용 그래프 | 헤드리스에서 추가 구성 없이 동작 |
| Plotly write_html, JS 내장 | dashboard.html | 오프라인 열람, 약 3 MB 증가 |
| Kaleido | 사용 안 함 | 1.0.0부터 Chrome 설치 필요 |
| python-docx | report.docx | Word 우선 생성 요건 |
| LibreOffice UNO | docx를 PDF로 변환 | 헤드리스 변환, autospace 제어 가능 |

### 4.8 docker exec 사용과 터미널 출력

| 항목 | 사양 |
|---|---|
| 컨테이너 | `--init --gpus all`로 상주, `sleep infinity` |
| GPU 할당 | `docker run` 시점에 고정 |
| 버퍼링 | `ENV PYTHONUNBUFFERED=1` |
| 출력 모드 | stdout이 TTY면 live, 아니면 plain, `--output json` 지원 |
| gpu-burn 원본 출력 | 터미널에 표시하지 않고 `logs/`로만 저장 |
| SIGINT, SIGTERM | 자식 프로세스 그룹 종료, 부분 레포트 생성, INCOMPLETE |
| SIGHUP | 무시하고 계속 진행 |
| 동시 실행 | `/results/.lock`으로 차단 |
| 잔여 프로세스 | 실행 전 gpu-burn 잔존 시 경고 후 중단 |
| 환경변수 | `LANG=C.UTF-8`, `MPLBACKEND=Agg`, `MPLCONFIGDIR=/tmp/matplotlib` |

| 종료 코드 | 의미 |
|---|---|
| 0 | PASS |
| 1 | WARN |
| 2 | FAIL |
| 3 | INCOMPLETE |
| 4 | 실행 오류 |

---

## 5. README 작성 요건

README는 **처음 레포를 접한 사람이 README만 보고 설치부터 결과 해석, 정리까지 끝낼 수 있어야** 합니다. CommonClaude 규칙에 따라 영어로 작성합니다. 아래 절은 모두 필수이며, 순서도 이대로 유지합니다.

| 순서 | 절 제목 | 필수 내용 |
|---|---|---|
| 1 | Overview | 도구가 하는 일, 대상 GPU, 소요 시간, 출력물 요약, A4 레포트 예시 이미지 |
| 2 | Requirements | 호스트 OS, NVIDIA 드라이버, Docker 버전, NVIDIA Container Toolkit, 디스크 여유 공간, 확인 명령과 기대 출력 |
| 3 | Get the Code | `git clone --recurse-submodules`, 이미 클론한 경우 `git submodule update --init --recursive` |
| 4 | Build the Image | `docker build` 명령, build arg 설명, 빌드 확인 명령 |
| 5 | Start the Container | 상주 컨테이너 생성 명령 전체, 각 옵션의 이유, 결과 폴더 마운트 |
| 6 | Run a Test | 프로필별 `docker exec -it` 실행, 소요 시간, 실행 중 화면 예시 |
| 7 | Long Runs over SSH | `docker exec -d`, `status`, `attach`, `stop` |
| 8 | Scripted and CI Use | `-t` 없이 실행, plain과 json 출력, 종료 코드 표 |
| 9 | Results | 결과 폴더 구조, 각 파일 설명, 호스트에서 여는 방법, report.docx를 수정한 뒤 PDF를 다시 만드는 방법 |
| 10 | Reading the Report | 판정 등급 의미, 각 규칙과 기준 출처, N/A가 나오는 조건, 참고값과 판정값 구분 |
| 11 | Re-rendering and Comparing | `plot`, `compare` 사용법, GPU 없는 PC에서 실행 가능함 |
| 12 | Configuration | `config/` 구조, 프로필 차이, 변경 가능한 항목 |
| 13 | Troubleshooting | GPU 미인식, 출력 지연, Ctrl+C 후 잔여 프로세스, 결과 파일 권한, Vulkan ICD 없음, PDF 변환 실패와 한글 글꼴 누락 등 증상별 조치 |
| 14 | Cleanup | 컨테이너 중지와 삭제, 이미지 삭제, 결과 정리 |
| 15 | Development | CommonClaude submodule, `scripts/setup_harness.sh`, 필수 MCP, 작업 절차, Verification Gate, 테스트 실행 |
| 16 | License and Third-party | 이 레포 라이선스, gpu-burn, cuda_memtest 등 포함 도구의 라이선스 |

| 규칙 | 내용 |
|---|---|
| 명령 검증 | README의 모든 명령은 실제로 실행해 확인한 것만 적습니다. CommonClaude의 문서 검증 규칙에 해당합니다 |
| 출력 예시 | 기대 출력은 실제 실행 결과에서 발췌합니다 |
| 끝까지 이어짐 | 3절부터 14절까지 순서대로 따라 하면 테스트 1회를 끝내고 정리까지 완료되어야 합니다 |
| 갱신 | CLI 옵션, 출력 파일, 판정 규칙이 바뀌는 PR은 README도 함께 수정합니다 |

---

## 6. 개발 단계

각 단계는 CommonClaude 작업 절차에 따라 ToDo.md 항목, GitHub issue, 브랜치, PR 단위로 진행합니다.

| 단계 | 내용 | 검증 방법 |
|---|---|---|
| M0 | external/CommonClaude submodule, 하네스 적용, 0.3절 확인 | 0.3절 확인 출력 |
| M1 | 레포 골격, pyproject, CI, fixture 수집 | CI 통과 |
| M2 | detect, sysinfo, telemetry | 실제 GPU에서 quick 실행, 운영자 입회 |
| M3 | gpu-burn, cuda_memtest runner와 파서 | fixture 테스트, 실제 GPU quick 실행 |
| M4 | analysis, evaluate | fixture 테스트 |
| M5 | charts, report.docx, docx2pdf | fixture로 docx와 PDF 생성, docx 스키마 검증, PDF 1페이지 확인 |
| M6 | console, runtime, docker exec 동작 | 실제 GPU에서 SIGINT, SIGHUP, stop 시나리오 |
| M7 | consumer, datacenter 옵션 runner | 각 계열 실제 장비 실행 |
| M8 | README 완성 | 5절 순서대로 새 호스트에서 처음부터 끝까지 재현 |
| M9 | v0.1.0 태그 | 전체 프로필 full 실행 결과 첨부 |

---

## 7. 참고 자료

| 항목 | 링크 |
|---|---|
| CommonClaude | https://github.com/coport-uni/CommonClaude |
| Claude Code memory, CLAUDE.md import | https://code.claude.com/docs/en/memory |
| Claude Code hooks | https://code.claude.com/docs/en/hooks |
| gpu-burn | https://github.com/wilicc/gpu-burn |
| cuda_memtest | https://github.com/ComputationalRadiationPhysics/cuda_memtest |
| memtest_vulkan | https://github.com/GpuZelenograd/memtest_vulkan |
| gpu-fryer | https://github.com/huggingface/gpu-fryer |
| DCGM Diagnostics | https://docs.nvidia.com/datacenter/dcgm/latest/user-guide/dcgm-diagnostics.html |
| DCGM Diagnostic Errors | https://docs.nvidia.com/datacenter/dcgm/latest/reference/diagnostics/errors.html |
| DCGM Memtest | https://docs.nvidia.com/datacenter/dcgm/latest/user-guide/diag-cuda-mats.html |
| NVML ClocksEventReasons | https://docs.nvidia.com/deploy/nvml-api/latest/api/group__nvmlClocksEventReasons.html |
| nvidia-smi | https://docs.nvidia.com/deploy/nvidia-smi/index.html |
| NVIDIA Container Toolkit | https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/docker-specialized.html |
| SuperBench | https://microsoft.github.io/superbenchmark/ |
| tini | https://github.com/krallin/tini |
| python-docx | https://python-docx.readthedocs.io/ |
| LibreOffice UNO API | https://api.libreoffice.org/ |
