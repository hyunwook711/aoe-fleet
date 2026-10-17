# aoe-fleet

[Agent of Empires](https://github.com/agent-of-empires/agent-of-empires)(AoE)는 대시보드 하나가 장비 한 대의 세션만 보여줍니다. 집에 있는 여러 장비에서 에이전트를 돌리면 어느 장비의 어떤 세션이 입력을 기다리는지 장비마다 들어가 봐야 해서, 각 장비의 `aoe serve` 세션 목록을 모아 메인 대시보드 한 패널에 보여주는 플러그인을 만들었습니다.

An AoE plugin that aggregates sessions from several machines' `aoe serve` daemons into one dashboard pane. UI text is Korean.

## 화면

대시보드 첫 화면에 "장비 · 세션" 패널이 붙습니다.

- 입력 대기·오류 세션이 있거나 연결이 끊긴 장비가 있으면 맨 위에 경고
- 장비마다 세션 목록: 오류 → 입력 대기 → 실행 중 순, 상태별 개수 배지
- 세션을 누르면 그 장비의 대시보드에서 해당 세션이 열림
- 연결되지 않는 장비는 "연결 끊김"과 오류 내용 표시

## 필요한 것

- AoE 1.17 이상, 각 장비에서 `aoe serve`
- Python 3.10 이상 (표준 라이브러리만 사용)
- 메인 장비에서 각 장비의 `aoe serve`에 닿는 사설망. 예: Tailscale과 `tailscale serve`로 tailnet 안에서만 HTTPS. `aoe serve --remote`는 Tailscale Funnel을 써서 인터넷에 공개되므로 권하지 않습니다.

## 설치

```bash
aoe plugin install gh:hyunwook711/aoe-fleet
aoe serve --restart
```

요청하는 권한: `runtime.worker`, `net`(각 장비의 `GET /api/sessions` 조회), `process.spawn`(`attach_agent`를 쓸 때 허브의 `aoe` CLI로 연결 세션 관리).

## 설정

대시보드 설정 → Fleet → 장비 목록

| 필드 | 설명 |
|---|---|
| `name` | 패널에 보일 장비 이름 |
| `url` | 그 장비의 `aoe serve` 주소 |
| `token_file` | 그 장비의 토큰을 담은 파일 경로(권한 600 권장). 토큰 자체는 설정에 넣지 않습니다 |
| `link_url` | (선택) 세션을 열 때 쓸 그 장비의 대시보드 주소. `url`이 SSH 터널 같은 로컬 주소일 때 지정합니다 |
| `attach_agent` | (선택) 이 허브의 AoE custom agent 이름. 예: `config.toml`에 `[session.custom_agents] lan-m4 = "ssh -t m4"`를 두고 `lan-m4`를 넣으면, 그 장비의 세션마다 허브에 연결 세션을 만들어 사설망 SSH로 원격 tmux에 붙습니다. 원격 장비를 인터넷에 열지 않고 메인 대시보드 한 곳에서 모든 세션을 엽니다. 원격 세션이 끝나면 연결 세션도 지웁니다 |
| `mirror_skip_groups` | (선택, 전체 설정) 연결 세션을 만들지 않을 원격 세션 그룹 목록. 허브가 붙으면 화면 크기가 바뀌어 곤란한 상시 세션용 |
| `tmux_bin` | (선택) 그 장비의 tmux 경로. 기본 `tmux`, macOS Homebrew는 `/opt/homebrew/bin/tmux` |

목록이 비어 있으면 이 장비(`http://127.0.0.1:8080`)만 보여주고, 로컬 주소는 `~/.agent-of-empires/serve.token`을 자동으로 씁니다.

## 한계

- `attach_agent`가 없는 장비는 링크로 그 장비의 대시보드를 엽니다.
- 장비 상태는 주기적으로 물어봐서 갱신합니다. AoE의 `callback_url`은 사설 주소로 알림을 보내지 않습니다.
- 이 장비 한 대와 일부러 닿지 않게 한 주소로만 시험했습니다. 실제 다른 장비의 `aoe serve`에 붙여 본 적은 아직 없습니다.

## 테스트

```bash
python3 -m unittest discover -s tests -v
```

## License

MIT
