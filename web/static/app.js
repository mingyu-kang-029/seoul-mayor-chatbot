/* ═══════════════════════════════════════════
   전역 상태
═══════════════════════════════════════════ */
const CANDIDATE_ORDER = ['정원오', '오세훈', '김정철'];

const PARTY_COLORS = {
  '더불어민주당': { border: '#1D4ED8', bg: 'rgba(29,78,216,0.05)', label: '#1D4ED8' },
  '국민의힘':    { border: '#DC2626', bg: 'rgba(220,38,38,0.05)',  label: '#DC2626' },
  '개혁신당':    { border: '#D97706', bg: 'rgba(217,119,6,0.05)',  label: '#D97706' },
};

const state = {
  candidates: [],
  dataDate: null,
  profile: {},
  recommendations: [],
  comparisons: {},
  loadingTopics: new Set(),
  // 토픽별 후보별 대화 히스토리 (클라이언트 메모리 전용 — DB/API에 저장 안 함)
  agentHistories: {},
};

/* ═══════════════════════════════════════════
   뷰 전환
═══════════════════════════════════════════ */
function showView(id) {
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

/* ═══════════════════════════════════════════
   초기 데이터 로드
═══════════════════════════════════════════ */
async function init() {
  initChips();

  // 후보 정보 + 데이터 기준일 병렬 요청
  const [candRes, infoRes] = await Promise.allSettled([
    fetch('/api/candidates').then(r => r.json()),
    fetch('/api/data-info').then(r => r.json()),
  ]);

  if (candRes.status === 'fulfilled') {
    state.candidates = candRes.value.candidates || [];
    renderCandidateIntros();
  }
  if (infoRes.status === 'fulfilled' && infoRes.value.latest_date) {
    state.dataDate = infoRes.value.latest_date;
  }

  showView('view-filter');
}

/* ═══════════════════════════════════════════
   후보 소개 카드 렌더링
═══════════════════════════════════════════ */
function renderCandidateIntros() {
  const grid = document.getElementById('candidate-intro-grid');
  grid.innerHTML = '';
  state.candidates.forEach(c => {
    const card = document.createElement('div');
    card.className = 'candidate-intro-card';
    card.innerHTML = `
      <img class="candidate-intro-photo"
           src="${c.photo}"
           alt="${c.name} 후보"
           onerror="this.style.display='none'" />
      <div class="candidate-intro-info">
        <div class="candidate-intro-number">기호 ${c.number}번</div>
        <div class="candidate-intro-name">${c.name}</div>
        <span class="candidate-intro-party">${c.party}</span>
        <div class="candidate-intro-career">${c.career_short}</div>
      </div>
    `;
    grid.appendChild(card);
  });
}

/* ═══════════════════════════════════════════
   칩 선택 초기화
═══════════════════════════════════════════ */
function initChips() {
  document.querySelectorAll('.chip-group').forEach(group => {
    const isMulti = group.dataset.multi === 'true';
    group.querySelectorAll('.chip').forEach(chip => {
      chip.addEventListener('click', () => {
        if (isMulti) {
          chip.classList.toggle('selected');
        } else {
          group.querySelectorAll('.chip').forEach(c => c.classList.remove('selected'));
          chip.classList.add('selected');
        }
      });
    });
  });
}

/* ═══════════════════════════════════════════
   프로필 수집
═══════════════════════════════════════════ */
function collectProfile() {
  const profile = {};
  document.querySelectorAll('.chip-group').forEach(group => {
    const key = group.dataset.key;
    if (!key) return;
    const isMulti = group.dataset.multi === 'true';
    const selected = [...group.querySelectorAll('.chip.selected')].map(c => c.dataset.value);
    profile[key] = isMulti ? selected : (selected[0] || null);
  });
  profile.freetext = document.getElementById('freetext').value.trim();
  return profile;
}

/* ═══════════════════════════════════════════
   폼 제출
═══════════════════════════════════════════ */
document.getElementById('filter-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  state.profile = collectProfile();

  showView('view-loading');
  document.getElementById('loading-msg').textContent = '관련 정책 분야를 분석하는 중...';

  try {
    const res = await fetch('/api/recommend', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(state.profile),
    });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    state.recommendations = data.topics || [];
    state.comparisons = {};
    renderResults();
    showView('view-results');
  } catch (err) {
    alert('분석 중 오류가 발생했습니다. 다시 시도해 주세요.\n' + err.message);
    showView('view-filter');
  }
});

/* ═══════════════════════════════════════════
   결과 화면 렌더링
═══════════════════════════════════════════ */
function renderResults() {
  // 데이터 기준일 배지
  const badge = document.getElementById('data-freshness-badge');
  badge.textContent = state.dataDate
    ? `데이터 기준: ${state.dataDate.replace(/-/g, '.')}`
    : '';

  const list = document.getElementById('topics-list');
  list.innerHTML = '';
  state.loadingTopics.clear();

  state.recommendations.forEach((item, idx) => {
    list.appendChild(buildTopicCard(item, idx + 1));
  });

  // 3개 전부 백그라운드 프리패치
  state.recommendations.forEach(item => prefetchComparison(item.topic));
}

function prefetchComparison(topic) {
  if (state.comparisons[topic] || state.loadingTopics.has(topic)) return;
  state.loadingTopics.add(topic);
  fetch('/api/compare', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ topic, profile: state.profile }),
  })
    .then(r => r.ok ? r.json() : Promise.reject())
    .then(data => {
      state.comparisons[topic] = data;
      // 이미 열려 있는 카드에 렌더링 (클릭 시 로딩 중이어서 return된 경우 처리)
      const card = document.querySelector(`.topic-card[data-topic="${CSS.escape(topic)}"]`);
      if (card) {
        const content = card.querySelector('.topic-content');
        const inner = card.querySelector('.topic-content-inner');
        if (content && content.classList.contains('open') && inner && inner.children.length === 0) {
          renderComparison(topic, inner, data);
        }
      }
    })
    .catch(() => {})
    .finally(() => { state.loadingTopics.delete(topic); });
}

/* ═══════════════════════════════════════════
   토픽 카드
═══════════════════════════════════════════ */
function buildTopicCard(item, rank) {
  const tpl = document.getElementById('tpl-topic-card');
  const card = tpl.content.cloneNode(true).querySelector('.topic-card');

  card.dataset.topic = item.topic;
  card.querySelector('.topic-rank').textContent = String(rank).padStart(2, '0');
  card.querySelector('.topic-name').textContent = item.topic;
  card.querySelector('.topic-reason').textContent = item.reason;

  const header  = card.querySelector('.topic-card-header');
  const btn     = card.querySelector('.topic-toggle-btn');
  const content = card.querySelector('.topic-content');
  const inner   = card.querySelector('.topic-content-inner');

  header.addEventListener('click', () => toggleTopic(item.topic, btn, content, inner));
  return card;
}

/* ═══════════════════════════════════════════
   토픽 토글 & 레이지 로드
═══════════════════════════════════════════ */
async function toggleTopic(topic, btn, content, inner) {
  const isOpen = content.classList.contains('open');

  if (isOpen) {
    content.classList.remove('open');
    btn.classList.remove('open');
    btn.querySelector('.toggle-label').textContent = '비교 보기';
    btn.setAttribute('aria-expanded', 'false');
    return;
  }

  content.classList.add('open');
  btn.classList.add('open');
  btn.querySelector('.toggle-label').textContent = '접기';
  btn.setAttribute('aria-expanded', 'true');

  if (state.comparisons[topic]) {
    // 이미 렌더링된 경우 재렌더링하지 않음 (에이전트 대화 내역 보존)
    if (inner.children.length === 0) {
      renderComparison(topic, inner, state.comparisons[topic]);
    }
    return;
  }
  if (state.loadingTopics.has(topic)) return;
  state.loadingTopics.add(topic);

  inner.innerHTML = `
    <div class="compare-loading">
      <span class="mini-spinner"></span>
      후보들의 입장을 분석하는 중...
    </div>`;

  try {
    const res = await fetch('/api/compare', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ topic, profile: state.profile }),
    });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    state.comparisons[topic] = data;
    renderComparison(topic, inner, data);
  } catch {
    inner.innerHTML = `<p class="error-msg">분석 중 오류가 발생했습니다. 카드를 닫고 다시 시도해 주세요.</p>`;
  } finally {
    state.loadingTopics.delete(topic);
  }
}

/* ═══════════════════════════════════════════
   비교 결과 렌더링
═══════════════════════════════════════════ */
function renderComparison(topic, container, data) {
  container.innerHTML = '';

  /* ── 0. 나에게 어떤 의미? (user_impact) ── */
  const userImpact = (data.user_impact || '').trim();
  if (userImpact) {
    const impactBox = document.createElement('div');
    impactBox.className = 'user-impact-box';
    impactBox.innerHTML = `
      <div class="user-impact-label">내 상황에서 주목할 점</div>
      <p class="user-impact-text">${userImpact}</p>
    `;
    container.appendChild(impactBox);
  }

  /* ── 1. 후보별 입장 요약 ── */
  const stanceSection = document.createElement('div');
  stanceSection.className = 'subsection';

  const stanceHeader = document.createElement('div');
  stanceHeader.className = 'subsection-header';
  stanceHeader.innerHTML = `
    <span class="subsection-label">후보별 입장</span>
    <span class="ai-badge">AI 요약</span>
  `;
  stanceSection.appendChild(stanceHeader);

  const grid = document.createElement('div');
  grid.className = 'candidates-grid';
  (data.candidates || []).forEach(c => grid.appendChild(buildCandidateCard(c)));
  stanceSection.appendChild(grid);
  container.appendChild(stanceSection);

  /* ── 2. 반박 대결 구조 ── */
  const debateItems = data.debate || [];
  const clashSection = document.createElement('div');
  clashSection.className = 'subsection clash-section';

  const clashHeader = document.createElement('div');
  clashHeader.className = 'subsection-header';
  clashHeader.innerHTML = `<span class="subsection-label">입장 차이</span>`;
  clashSection.appendChild(clashHeader);

  const summary = data.clash_summary || '';
  if (summary && !summary.includes('충분하지 않')) {
    const p = document.createElement('p');
    p.className = 'clash-summary-text';
    p.textContent = summary;
    clashSection.appendChild(p);
  }

  if (debateItems.length > 0) {
    const debateWrap = document.createElement('div');
    debateWrap.className = 'debate-wrap';
    debateItems.forEach(item => debateWrap.appendChild(buildDebateBlock(item)));
    clashSection.appendChild(debateWrap);
  } else {
    const note = document.createElement('p');
    note.className = 'no-clash-note';
    note.textContent = summary.includes('충분하지 않')
      ? summary
      : '비교 가능한 입장 차이를 찾지 못했습니다.';
    clashSection.appendChild(note);
  }
  container.appendChild(clashSection);

  /* ── 3. 원문 근거 서랍 ── */
  const sources = data.sources || {};
  const hasAnySrc = Object.values(sources).some(arr => arr.length > 0);
  if (hasAnySrc) {
    container.appendChild(buildSourceDrawer(sources));
  }

  /* ── 4. AI 토론 패널 ── */
  container.appendChild(buildLiveDebatePanel(topic, data));

  /* ── 5. 에이전트 채팅 패널 ── */
  container.appendChild(buildAgentPanel(topic));
}

/* ═══════════════════════════════════════════
   후보 카드
═══════════════════════════════════════════ */
function buildCandidateCard(c) {
  const card = document.createElement('div');
  card.className = 'candidate-card' + (c.has_data ? '' : ' no-data');
  const pc = PARTY_COLORS[c.party];
  if (pc && c.has_data) {
    card.style.borderLeftColor = pc.border;
    card.style.borderLeftWidth = '3px';
  }
  card.innerHTML = `
    <div>
      <div class="cand-name">${c.name}</div>
      <div class="cand-party" style="${pc && c.has_data ? `color:${pc.label};` : ''}">${c.party}</div>
    </div>
    <p class="cand-stance">${c.stance}</p>
  `;
  return card;
}

/* ═══════════════════════════════════════════
   충돌 비교 카드
═══════════════════════════════════════════ */
function getCandidateParty(name) {
  const c = state.candidates.find(c => c.name === name);
  return c ? c.party : '';
}

function buildClashCard(clash) {
  const card = document.createElement('div');
  card.className = 'clash-card';

  const leftParty  = getCandidateParty(clash.left.name);
  const rightParty = getCandidateParty(clash.right.name);
  const lcLeft  = PARTY_COLORS[leftParty]  || {};
  const lcRight = PARTY_COLORS[rightParty] || {};

  const contrastHtml = clash.contrast
    ? `<div class="clash-contrast">${clash.contrast}</div>`
    : '';

  card.innerHTML = `
    <div class="clash-issue">${clash.issue}</div>
    ${contrastHtml}
    <div class="clash-body">
      <div class="clash-col" style="${lcLeft.bg ? `background:${lcLeft.bg};` : ''}">
        <div class="clash-col-name">${clash.left.name}</div>
        <span class="clash-col-label" style="${lcLeft.label ? `background:${lcLeft.label};color:#fff;` : ''}">${clash.left.label}</span>
        <p class="clash-col-detail">${clash.left.detail}</p>
      </div>
      <div class="clash-divider"></div>
      <div class="clash-col" style="${lcRight.bg ? `background:${lcRight.bg};` : ''}">
        <div class="clash-col-name">${clash.right.name}</div>
        <span class="clash-col-label" style="${lcRight.label ? `background:${lcRight.label};color:#fff;` : ''}">${clash.right.label}</span>
        <p class="clash-col-detail">${clash.right.detail}</p>
      </div>
    </div>
  `;
  return card;
}

/* ═══════════════════════════════════════════
   반박 대결 블록
═══════════════════════════════════════════ */
function buildDebateBlock(item) {
  const candInfo = getCandInfo(item.candidate);
  const party = candInfo.party || '';
  const pc = PARTY_COLORS[party] || {};

  const block = document.createElement('div');
  block.className = 'debate-block';

  // 주장 헤더
  const claimEl = document.createElement('div');
  claimEl.className = 'debate-claim';
  claimEl.style.borderLeftColor = pc.border || '#ccc';
  claimEl.innerHTML = `
    <div class="debate-claim-meta">
      <span class="debate-cand-name" style="color:${pc.label || 'inherit'}">${item.candidate}</span>
      <span class="debate-cand-party">${party}</span>
    </div>
    <p class="debate-key-claim">${item.key_claim || ''}</p>
  `;
  block.appendChild(claimEl);

  // 반박 카드들
  const rebuttals = item.rebuttals || [];
  if (rebuttals.length > 0) {
    const rebuttalList = document.createElement('div');
    rebuttalList.className = 'rebuttal-list';
    rebuttals.forEach(r => {
      const rInfo = getCandInfo(r.from);
      const rParty = rInfo.party || '';
      const rpc = PARTY_COLORS[rParty] || {};

      const rCard = document.createElement('div');
      rCard.className = 'rebuttal-card';
      rCard.innerHTML = `
        <div class="rebuttal-from">
          <span class="rebuttal-arrow">↳</span>
          <span class="rebuttal-name" style="color:${rpc.label || 'inherit'}">${r.from}</span>
          <span class="rebuttal-angle">${r.angle || ''}</span>
        </div>
        <p class="rebuttal-text">${r.text || ''}</p>
      `;
      rebuttalList.appendChild(rCard);
    });
    block.appendChild(rebuttalList);
  } else {
    const noRebuttal = document.createElement('p');
    noRebuttal.className = 'no-rebuttal-note';
    noRebuttal.textContent = '다른 후보의 공식 입장이 없어 반박을 구성할 수 없습니다.';
    block.appendChild(noRebuttal);
  }

  return block;
}

/* ═══════════════════════════════════════════
   원문 근거 서랍
═══════════════════════════════════════════ */
function buildSourceDrawer(sources) {
  const wrapper = document.createElement('div');
  wrapper.className = 'source-drawer-wrapper';

  const toggle = document.createElement('button');
  toggle.className = 'source-drawer-toggle';
  toggle.innerHTML = `<span class="drawer-arrow">▸</span> 원문 근거 보기`;

  const drawer = document.createElement('div');
  drawer.className = 'source-drawer';

  const inner = document.createElement('div');
  inner.className = 'source-drawer-inner';

  CANDIDATE_ORDER.forEach(name => {
    const srcs = (sources[name] || []).filter(s => s.source_name || s.title);
    if (!srcs.length) return;

    const sec = document.createElement('div');
    sec.className = 'source-cand-section';

    const nameEl = document.createElement('div');
    nameEl.className = 'source-cand-name';
    nameEl.textContent = `${name}  (${srcs.length}건)`;
    sec.appendChild(nameEl);

    // 중복 source_name 제거
    const seen = new Set();
    srcs.forEach(s => {
      const key = s.source_name || s.title;
      if (seen.has(key)) return;
      seen.add(key);

      const item = document.createElement('div');
      item.className = 'source-item';

      const label = s.title || s.source_name || '원문';
      const titleEl = s.source_url
        ? `<a href="${s.source_url}" target="_blank" rel="noopener noreferrer">${label}</a>`
        : `<span>${label}</span>`;
      const dateEl = s.date ? `<span class="source-item-date">${s.date}</span>` : '';

      item.innerHTML = `
        <span class="source-type-tag">${s.source_type}</span>
        <span class="source-item-title">${titleEl}</span>
        ${dateEl}
      `;
      sec.appendChild(item);
    });

    inner.appendChild(sec);
  });

  drawer.appendChild(inner);
  wrapper.appendChild(toggle);
  wrapper.appendChild(drawer);

  toggle.addEventListener('click', () => {
    const open = drawer.classList.toggle('open');
    toggle.innerHTML = open
      ? `<span class="drawer-arrow">▾</span> 원문 근거 접기`
      : `<span class="drawer-arrow">▸</span> 원문 근거 보기`;
  });

  return wrapper;
}

/* ═══════════════════════════════════════════
   뒤로 가기
═══════════════════════════════════════════ */
document.getElementById('btn-back').addEventListener('click', () => {
  showView('view-filter');
});

/* ═══════════════════════════════════════════
   헬퍼
═══════════════════════════════════════════ */
function getCandInfo(name) {
  return state.candidates.find(c => c.name === name) || { party: '' };
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/* ═══════════════════════════════════════════
   AI 토론 패널 빌더
═══════════════════════════════════════════ */
function buildLiveDebatePanel(topic, compareData) {
  const candidatesWithData = (compareData.candidates || [])
    .filter(c => c.has_data)
    .map(c => c.name);

  const panel = document.createElement('div');
  panel.className = 'live-debate-panel';

  const header = document.createElement('div');
  header.className = 'agent-panel-header';
  header.innerHTML = `
    <span class="subsection-label">AI 토론</span>
    <span class="agent-no-learn-badge">3라운드 · 공식 입장 기반</span>
  `;
  panel.appendChild(header);

  if (candidatesWithData.length < 2) {
    const note = document.createElement('p');
    note.className = 'no-clash-note';
    note.textContent = '토론을 진행하려면 공식 입장이 있는 후보가 2명 이상 필요합니다.';
    panel.appendChild(note);
    return panel;
  }

  // 설정 박스 — agent-input-area와 같은 컨테이너 스타일
  const setupEl = document.createElement('div');
  setupEl.className = 'agent-input-area debate-setup';

  // 내 입장 입력
  const claimRow = document.createElement('div');
  claimRow.innerHTML = `
    <div class="agent-target-row" style="margin-bottom:8px">
      <span class="agent-target-label">내 입장</span>
    </div>
    <textarea class="agent-textarea debate-claim-input" rows="2"
      placeholder="예: 임대주택 확대가 집값 안정에 효과적이라고 생각한다"></textarea>
  `;
  setupEl.appendChild(claimRow);

  // 후보 선택 — chip 방식
  // 각 그룹에서 하나씩 선택, 기본값 첫번째 vs 두번째
  const selA = { value: candidatesWithData[0] };
  const selB = { value: candidatesWithData[1] };

  function buildCandChips(sel, otherSel, groupClass) {
    const row = document.createElement('div');
    row.className = 'agent-target-row';
    row.innerHTML = `<span class="agent-target-label">${groupClass === 'cand-a' ? '주장' : '반박'}</span>`;
    const chips = document.createElement('div');
    chips.className = 'agent-target-chips';
    candidatesWithData.forEach(name => {
      const info = getCandInfo(name);
      const pc = PARTY_COLORS[info.party] || {};
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'agent-target-chip debate-cand-chip' + (name === sel.value ? ' selected' : '');
      btn.dataset.name = name;
      btn.innerHTML = `<span style="color:${pc.label||'inherit'}">${name}</span>`;
      btn.addEventListener('click', () => {
        sel.value = name;
        chips.querySelectorAll('.debate-cand-chip').forEach(c => c.classList.remove('selected'));
        btn.classList.add('selected');
      });
      chips.appendChild(btn);
    });
    row.appendChild(chips);
    return row;
  }

  setupEl.appendChild(buildCandChips(selA, selB, 'cand-a'));
  setupEl.appendChild(buildCandChips(selB, selA, 'cand-b'));

  // 시작 버튼 — agent-send-btn 스타일 재사용
  const inputRow = document.createElement('div');
  inputRow.className = 'agent-input-row';
  inputRow.style.justifyContent = 'flex-end';
  const startBtn = document.createElement('button');
  startBtn.type = 'button';
  startBtn.className = 'agent-send-btn';
  startBtn.textContent = '토론 시작';
  inputRow.appendChild(startBtn);
  setupEl.appendChild(inputRow);

  panel.appendChild(setupEl);

  // 결과 영역
  const resultEl = document.createElement('div');
  resultEl.className = 'debate-result';
  resultEl.style.display = 'none';
  panel.appendChild(resultEl);

  // 판정 영역
  const verdictEl = document.createElement('div');
  verdictEl.className = 'debate-verdict';
  verdictEl.style.display = 'none';

  const verdictTextarea = document.createElement('textarea');
  verdictTextarea.className = 'agent-textarea debate-claim-input';
  verdictTextarea.rows = 2;
  verdictTextarea.placeholder = '예: 오세훈 후보 — 공급 확대의 구체적 수치가 더 설득력 있었다';

  const verdictConfirmRow = document.createElement('div');
  verdictConfirmRow.className = 'agent-input-row';
  verdictConfirmRow.style.justifyContent = 'space-between';
  verdictConfirmRow.style.alignItems = 'center';
  verdictConfirmRow.innerHTML = `<p class="debate-verdict-hint" style="margin:0">직접 정리하면 투표 판단이 더 선명해집니다.</p>`;

  const verdictSaveBtn = document.createElement('button');
  verdictSaveBtn.type = 'button';
  verdictSaveBtn.className = 'agent-send-btn';
  verdictSaveBtn.textContent = '기록하기';
  verdictConfirmRow.appendChild(verdictSaveBtn);

  const verdictDone = document.createElement('div');
  verdictDone.className = 'user-impact-box';
  verdictDone.style.display = 'none';
  verdictDone.innerHTML = `<div class="user-impact-label">내 판정</div><p class="user-impact-text"></p>`;

  verdictEl.innerHTML = `<div class="user-impact-label" style="margin-bottom:10px">어느 쪽 논리가 더 설득력 있었나요?</div>`;
  verdictEl.appendChild(verdictTextarea);
  verdictEl.appendChild(verdictConfirmRow);
  verdictEl.appendChild(verdictDone);

  verdictSaveBtn.addEventListener('click', () => {
    const text = verdictTextarea.value.trim();
    if (!text) { verdictTextarea.focus(); return; }
    verdictTextarea.style.display = 'none';
    verdictConfirmRow.style.display = 'none';
    verdictDone.style.display = 'block';
    verdictDone.querySelector('.user-impact-text').textContent = text;
  });

  panel.appendChild(verdictEl);

  startBtn.addEventListener('click', async () => {
    const userClaim = setupEl.querySelector('.debate-claim-input').value.trim();
    if (!userClaim) { setupEl.querySelector('.debate-claim-input').focus(); return; }
    if (selA.value === selB.value) { alert('서로 다른 후보를 선택해 주세요.'); return; }

    startBtn.disabled = true;
    startBtn.textContent = '생성 중...';
    resultEl.style.display = 'block';
    verdictEl.style.display = 'none';
    resultEl.innerHTML = `
      <div class="compare-loading">
        <span class="mini-spinner"></span>
        후보들이 토론을 준비하는 중...
      </div>`;

    try {
      const res = await fetch('/api/debate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          topic,
          candidate_a: selA.value,
          candidate_b: selB.value,
          user_claim: userClaim,
          profile: state.profile,
        }),
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      const rounds = data.rounds || [];
      renderDebateRounds(resultEl, rounds, userClaim, {
        topic, candA: selA.value, candB: selB.value, userClaim,
      }, verdictEl);
      verdictEl.style.display = 'block';
    } catch {
      resultEl.innerHTML = `<p class="error-msg">토론 생성 중 오류가 발생했습니다. 다시 시도해 주세요.</p>`;
    } finally {
      startBtn.disabled = false;
      startBtn.textContent = '다시 토론하기';
    }
  });

  return panel;
}

function renderDebateRounds(container, rounds, userClaim, debateCtx, verdictEl) {
  container.innerHTML = '';

  // 유저 입장
  const claimBanner = document.createElement('div');
  claimBanner.className = 'user-impact-box';
  claimBanner.innerHTML = `
    <div class="user-impact-label">내 입장</div>
    <p class="user-impact-text">${escapeHtml(userClaim)}</p>
  `;
  container.appendChild(claimBanner);

  // 라운드 카드들을 담을 래퍼 (추가 라운드 append 용)
  const roundsWrap = document.createElement('div');
  container.appendChild(roundsWrap);

  function appendRound(round) {
    const info = getCandInfo(round.candidate);
    const pc = PARTY_COLORS[info.party] || {};
    const el = document.createElement('div');
    el.className = 'rebuttal-card debate-round-card';
    el.innerHTML = `
      <div class="rebuttal-from" style="margin-bottom:8px">
        <span class="rebuttal-angle">${round.role} R${round.round}</span>
        <span class="rebuttal-name" style="color:${pc.label||'inherit'}">${round.candidate}</span>
        <span style="font-size:11px;color:var(--text-muted)">${info.party||''}</span>
      </div>
      <p class="rebuttal-text">${escapeHtml(round.text)}</p>
    `;
    roundsWrap.appendChild(el);
  }

  rounds.forEach(appendRound);

  // "1라운드 더" 버튼 (최대 5라운드까지)
  if (!debateCtx) return;

  const extendRow = document.createElement('div');
  extendRow.className = 'agent-input-row';
  extendRow.style.justifyContent = 'flex-end';
  extendRow.style.marginTop = '10px';

  const extendBtn = document.createElement('button');
  extendBtn.type = 'button';
  extendBtn.className = 'agent-target-chip';
  extendBtn.textContent = '1라운드 더 →';
  extendRow.appendChild(extendBtn);
  container.appendChild(extendRow);

  let currentRounds = [...rounds];

  extendBtn.addEventListener('click', async () => {
    if (currentRounds.length >= 5) {
      extendBtn.textContent = '최대 5라운드까지 가능합니다';
      extendBtn.disabled = true;
      return;
    }

    extendBtn.disabled = true;
    extendBtn.textContent = '생성 중...';
    if (verdictEl) verdictEl.style.display = 'none';

    try {
      const res = await fetch('/api/debate/extend', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          topic: debateCtx.topic,
          candidate_a: debateCtx.candA,
          candidate_b: debateCtx.candB,
          user_claim: debateCtx.userClaim,
          previous_rounds: currentRounds,
        }),
      });
      if (!res.ok) throw new Error(await res.text());
      const newRound = await res.json();
      currentRounds.push(newRound);
      appendRound(newRound);

      if (currentRounds.length >= 5) {
        extendBtn.textContent = '5라운드 완료';
        extendBtn.disabled = true;
      } else {
        extendBtn.disabled = false;
        extendBtn.textContent = '1라운드 더 →';
      }
    } catch {
      extendBtn.disabled = false;
      extendBtn.textContent = '다시 시도';
    } finally {
      if (verdictEl) verdictEl.style.display = 'block';
    }
  });
}

/* ═══════════════════════════════════════════
   에이전트 채팅 패널 빌더
═══════════════════════════════════════════ */
function buildAgentPanel(topic) {
  // 토픽별 히스토리 초기화 (없을 때만)
  if (!state.agentHistories[topic]) {
    state.agentHistories[topic] = {
      정원오: [],
      오세훈: [],
      김정철: [],
    };
  }

  const panel = document.createElement('div');
  panel.className = 'agent-panel';
  panel.dataset.topic = topic;

  panel.innerHTML = `
    <div class="agent-panel-header">
      <span class="subsection-label">후보에게 직접 질문하기</span>
      <span class="agent-no-learn-badge">공식 입장 기반 · 학습 없음</span>
    </div>
    <div class="agent-chat-history"></div>
    <div class="agent-input-area">
      <div class="agent-target-row">
        <span class="agent-target-label">대상</span>
        <div class="agent-target-chips">
          <button type="button" class="agent-target-chip selected" data-target="all">전체에게</button>
          <button type="button" class="agent-target-chip" data-target="정원오">정원오</button>
          <button type="button" class="agent-target-chip" data-target="오세훈">오세훈</button>
          <button type="button" class="agent-target-chip" data-target="김정철">김정철</button>
        </div>
      </div>
      <div class="agent-input-row">
        <textarea class="agent-textarea" rows="2"
          placeholder="후보에게 궁금한 점을 입력하세요. Shift+Enter 줄바꿈, Enter 전송"></textarea>
        <button type="button" class="agent-send-btn">전송</button>
      </div>
    </div>
  `;

  // 대상 칩 토글
  const targetChips = panel.querySelectorAll('.agent-target-chip');
  targetChips.forEach(chip => {
    chip.addEventListener('click', () => {
      targetChips.forEach(c => c.classList.remove('selected'));
      chip.classList.add('selected');
    });
  });

  const textarea  = panel.querySelector('.agent-textarea');
  const sendBtn   = panel.querySelector('.agent-send-btn');
  const historyEl = panel.querySelector('.agent-chat-history');

  const doSend = async () => {
    const question = textarea.value.trim();
    if (!question) return;

    const selectedTarget = panel.querySelector('.agent-target-chip.selected')?.dataset.target || 'all';
    const targets = selectedTarget === 'all' ? CANDIDATE_ORDER : [selectedTarget];

    textarea.value = '';
    textarea.disabled = true;
    sendBtn.disabled = true;
    sendBtn.textContent = '...';

    await askAgents(topic, question, targets, historyEl);

    textarea.disabled = false;
    sendBtn.disabled = false;
    sendBtn.textContent = '전송';
    textarea.focus();
  };

  sendBtn.addEventListener('click', doSend);
  textarea.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      doSend();
    }
  });

  return panel;
}

/* ═══════════════════════════════════════════
   에이전트 질의 & 렌더링
═══════════════════════════════════════════ */
async function askAgents(topic, question, targets, historyEl) {
  const targetLabel = targets.length === CANDIDATE_ORDER.length
    ? '전체에게'
    : targets.map(n => n).join(', ') + '에게';

  // 질문 + 응답 턴 컨테이너
  const turnEl = document.createElement('div');
  turnEl.className = 'chat-turn';
  turnEl.innerHTML = `
    <div class="chat-question">
      <span class="chat-q-label">Q</span>
      <span class="chat-q-target">${escapeHtml(targetLabel)}</span>
      <span class="chat-q-text">${escapeHtml(question)}</span>
    </div>
  `;

  const answersEl = document.createElement('div');
  answersEl.className = 'chat-answers';
  answersEl.dataset.count = targets.length;
  turnEl.appendChild(answersEl);
  historyEl.appendChild(turnEl);
  historyEl.scrollTop = historyEl.scrollHeight;

  // 후보별 로딩 카드 생성
  const cardMap = {};
  targets.forEach(name => {
    const info = getCandInfo(name);
    const card = document.createElement('div');
    card.className = 'chat-answer-card';
    card.innerHTML = `
      <div class="chat-answer-header">
        <span class="chat-answer-name">${name}</span>
        <span class="chat-answer-party" style="color:${getPartyColor(info.party)}">${info.party || ''}</span>
      </div>
      <div class="chat-answer-text">
        <span class="mini-spinner"></span>
      </div>
    `;
    cardMap[name] = card;
    answersEl.appendChild(card);
  });

  // 병렬 호출 — DB는 읽기 전용, 히스토리는 메모리에만
  const promises = targets.map(async name => {
    const history = state.agentHistories[topic][name] || [];
    try {
      const res = await fetch('/api/agent', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ candidate: name, topic, question, history }),
      });
      if (!res.ok) throw new Error(await res.text());
      const { answer } = await res.json();

      // 히스토리 업데이트 (메모리만)
      state.agentHistories[topic][name] = [
        ...history,
        { role: 'user', content: question },
        { role: 'assistant', content: answer },
      ];

      cardMap[name].querySelector('.chat-answer-text').textContent = answer;
    } catch (err) {
      console.error(`[agent] ${name} 응답 실패:`, err);
      cardMap[name].querySelector('.chat-answer-text').innerHTML =
        '<span class="agent-error">답변을 불러오지 못했습니다.</span>';
    }
  });

  await Promise.all(promises);
  historyEl.scrollTop = historyEl.scrollHeight;
}

function getPartyColor(party) {
  const colors = {
    '더불어민주당': '#1D4ED8',
    '국민의힘': '#DC2626',
    '개혁신당': '#D97706',
  };
  return colors[party] || 'var(--text-muted)';
}

/* ═══════════════════════════════════════════
   시작
═══════════════════════════════════════════ */
init();
