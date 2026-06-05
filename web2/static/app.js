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

  // URL에 ?topic= 파라미터가 있으면 공유된 비교 결과를 바로 표시
  const sharedTopic = new URLSearchParams(location.search).get('topic');
  if (sharedTopic) {
    await showSharedTopic(sharedTopic);
  } else {
    showView('view-filter');
  }
}

async function showSharedTopic(topic) {
  // 필터 없이 비교 결과만 바로 노출
  state.profile = {};
  state.recommendations = [{ topic, reason: '공유된 링크로 바로 표시됩니다.' }];
  state.comparisons = {};

  renderResults();
  showView('view-results');

  // 공유 배너 표시
  const header = document.querySelector('.results-header');
  if (header && !header.querySelector('.shared-banner')) {
    const banner = document.createElement('div');
    banner.className = 'shared-banner';
    banner.innerHTML = `
      <span>🔗 공유된 비교 링크</span>
      <button onclick="history.replaceState(null,'',location.pathname);showView('view-filter')" class="shared-banner-btn">
        내 맞춤 분석 받기 →
      </button>`;
    header.prepend(banner);
  }
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
    card.setAttribute('role', 'button');
    card.setAttribute('tabindex', '0');
    card.title = `${c.name} 후보 상세 정보 보기`;
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
      <div class="candidate-intro-detail-hint">상세 정보 보기 ›</div>
    `;
    card.addEventListener('click', () => openCandidateModal(c));
    card.addEventListener('keydown', e => { if (e.key === 'Enter') openCandidateModal(c); });
    grid.appendChild(card);
  });
}

/* ═══════════════════════════════════════════
   후보자 상세 정보 모달
═══════════════════════════════════════════ */
function formatAsset(val) {
  if (val == null) return '정보없음';
  // val 단위: 천원 → 만원으로 변환
  const manwon = Math.round(val / 10);
  if (manwon >= 10000) {
    // 억 단위
    const uk = manwon / 10000;
    return `${uk % 1 === 0 ? uk : uk.toFixed(1)}억원`;
  }
  return `${manwon.toLocaleString()}만원`;
}

function formatTax(val) {
  if (val == null) return '정보없음';
  // val 단위: 천원 → 만원으로 변환
  const manwon = Math.round(val / 10);
  if (manwon >= 10000) {
    const uk = manwon / 10000;
    return `${uk % 1 === 0 ? uk : uk.toFixed(1)}억원`;
  }
  // 천만 단위 표기: 8,442만원
  return `${manwon.toLocaleString()}만원`;
}

function openCandidateModal(c) {
  const partyColor = {
    '더불어민주당': '#004EA2',
    '국민의힘': '#C9151E',
    '개혁신당': '#FF6600',
  }[c.party] || '#666';

  const criminalHtml = (c.criminal_record && c.criminal_record !== '해당없음' && c.criminal_record !== '정보없음')
    ? `<span class="modal-badge badge-warning">전과 있음</span>
       <p class="modal-criminal-detail">${c.criminal_record.replace(/\n/g, '<br>')}</p>`
    : `<span class="modal-badge badge-ok">${c.criminal_record || '정보없음'}</span>`;

  document.getElementById('candidate-modal-body').innerHTML = `
    <div class="modal-cand-header">
      <img src="${c.photo}" alt="${c.name}" class="modal-cand-photo"
           onerror="this.style.display='none'">
      <div>
        <div class="modal-cand-number" style="color:${partyColor}">기호 ${c.number}번</div>
        <div class="modal-cand-name">${c.name}</div>
        <span class="modal-cand-party" style="background:${partyColor}">${c.party}</span>
      </div>
    </div>
    <table class="modal-info-table">
      <tr>
        <th>학력</th>
        <td>${c.education_full || c.education || '정보없음'}</td>
      </tr>
      <tr>
        <th>경력</th>
        <td>${(c.career_db || c.career_full || '정보없음').replace(/\s*\/\s*/g, '<br>')}</td>
      </tr>
      <tr>
        <th>병역</th>
        <td>${c.military_service || '정보없음'}</td>
      </tr>
      <tr>
        <th>재산 총액</th>
        <td>
          ${formatAsset(c.asset_total)}
          <span class="modal-asset-detail">(본인 ${formatAsset(c.asset_self)} / 배우자 ${formatAsset(c.asset_spouse)})</span>
        </td>
      </tr>
      <tr>
        <th>납세 실적<br><small>최근 5년</small></th>
        <td>${formatTax(c.tax_paid)}</td>
      </tr>
      <tr>
        <th>전과기록</th>
        <td>${criminalHtml}</td>
      </tr>
    </table>
    <p class="modal-source-note">※ 출처: 선거공보 (중앙선거관리위원회, 2026)</p>
  `;

  const modal = document.getElementById('candidate-modal');
  modal.classList.add('open');
  document.body.style.overflow = 'hidden';
}

function closeCandidateModal() {
  document.getElementById('candidate-modal').classList.remove('open');
  document.body.style.overflow = '';
}

// 모달 닫기 이벤트
document.addEventListener('DOMContentLoaded', () => {
  const modal = document.getElementById('candidate-modal');
  if (!modal) return;
  modal.addEventListener('click', e => {
    if (e.target === modal) closeCandidateModal();
  });
  document.getElementById('candidate-modal-close')?.addEventListener('click', closeCandidateModal);
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') closeCandidateModal();
  });
});

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
    const card = buildTopicCard(item, idx + 1);
    list.appendChild(card);
    // 1순위 카드 자동 열기
    if (idx === 0) {
      const btn     = card.querySelector('.topic-toggle-btn');
      const content = card.querySelector('.topic-content');
      const inner   = card.querySelector('.topic-content-inner');
      toggleTopic(item.topic, btn, content, inner);
    }
  });

  // 지역 관심 토글 — 클릭 시 lazy load
  initLocalInsightToggle();

  // 3개 전부 백그라운드 프리패치
  state.recommendations.forEach(item => prefetchComparison(item.topic));
}

const SOURCE_LABEL = {
  '실적':      { text: '실적',  cls: 'badge-track' },
  '토론발언':  { text: '토론',  cls: 'badge-debate' },
  '언론':      { text: '언론',  cls: 'badge-media' },
  '유튜브':    { text: '유튜브', cls: 'badge-yt' },
  '공약집':    { text: '공약',  cls: 'badge-pledge' },
  '선거공보':  { text: '공보',  cls: 'badge-pledge' },
  '당홈페이지': { text: '당',   cls: 'badge-pledge' },
};

function initLocalInsightToggle() {
  const btn     = document.getElementById('gu-search-btn');
  const select  = document.getElementById('gu-select');
  const section = document.getElementById('local-insight-section');
  if (!btn || !select || !section) return;

  section.hidden = true;
  select.value = '';

  btn.onclick = async () => {
    const gu = select.value;
    if (!gu) { select.focus(); return; }
    section.hidden = false;
    await fetchLocalInsight(gu);
  };
}

async function fetchLocalInsight(gu) {
  const section = document.getElementById('local-insight-section');
  if (!section) return;

  section.innerHTML = `
    <div class="local-insight-grid">
      ${CANDIDATE_ORDER.map(() => `
        <div class="local-insight-card skeleton">
          <div class="skeleton-line short"></div>
          <div class="skeleton-line long"></div>
          <div class="skeleton-line mid"></div>
        </div>`).join('')}
    </div>`;

  try {
    const res = await fetch(`/api/local-insight?gu=${encodeURIComponent(gu)}`);
    if (!res.ok) throw new Error();
    const data = await res.json();
    renderLocalInsight(data);
  } catch {
    section.innerHTML = '<p class="local-insight-error">정보를 불러오지 못했습니다.</p>';
  }
}

// 출처 신뢰도 순서 (높은 것이 먼저)
const SOURCE_TRUST = ['실적', '공약집', '선거공보', '토론발언', '언론', '당홈페이지', '유튜브'];
const SOURCE_ICON = {
  '실적':      '✅',
  '공약집':    '📋',
  '선거공보':  '📋',
  '토론발언':  '🎙',
  '언론':      '📰',
  '당홈페이지':'🏛',
  '유튜브':    '▶',
};

function _buildStmtItem(s) {
  const src  = SOURCE_LABEL[s.source_type] || { text: s.source_type, cls: '' };
  const icon = SOURCE_ICON[s.source_type] || '';
  const item = document.createElement('div');
  item.className = 'li-stmt-item';
  item.innerHTML = `
    <div class="li-stmt-meta">
      <span class="li-source-badge ${src.cls}">${icon} ${src.text}</span>
    </div>
    <p class="li-stmt-text">${s.summary}</p>`;
  return item;
}

function renderLocalInsight(data) {
  const section = document.getElementById('local-insight-section');
  if (!section) return;

  const gu = data.gu || '';

  // 섹션 헤더 + 범례
  const header = document.createElement('div');
  header.className = 'li-section-header';
  header.innerHTML = `
    <span class="li-section-title">${gu} 관련 수집된 발언</span>
    <span class="li-section-notice">출처별 신뢰도가 다릅니다</span>`;

  const legend = document.createElement('div');
  legend.className = 'li-source-legend';
  legend.innerHTML = `<span class="li-legend-label">신뢰도</span>
    <span class="li-source-badge badge-pledge">📋 공약</span>
    <span class="li-source-badge badge-track">✅ 실적</span>
    <span class="li-legend-arrow">›</span>
    <span class="li-source-badge badge-debate">🎙 토론</span>
    <span class="li-source-badge badge-media">📰 언론</span>
    <span class="li-legend-arrow">›</span>
    <span class="li-source-badge badge-yt">▶ 유튜브 (캠페인 발언)</span>`;

  // ── 공식 소스 그리드 ──
  const officialGrid = document.createElement('div');
  officialGrid.className = 'local-insight-grid';

  // ── 유튜브 캠페인 발언 그리드 ──
  const ytGrid = document.createElement('div');
  ytGrid.className = 'local-insight-grid li-yt-grid';

  let hasYt = false;

  CANDIDATE_ORDER.forEach(name => {
    const cand   = state.candidates.find(c => c.name === name) || {};
    const pc     = PARTY_COLORS[cand.party] || {};
    const stmts  = data.candidates?.[name]?.statements    || [];
    const ytStmts = data.candidates?.[name]?.yt_statements || [];

    // 신뢰도 높은 순 정렬
    const sorted = [...stmts].sort((a, b) => {
      const ai = SOURCE_TRUST.indexOf(a.source_type);
      const bi = SOURCE_TRUST.indexOf(b.source_type);
      return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi);
    });

    // 공식 카드
    const card = document.createElement('div');
    card.className = 'local-insight-card';
    if (pc.border) card.style.borderTopColor = pc.border;
    card.innerHTML = `<div class="li-card-header">
      <span class="li-cand-name" style="color:${pc.label || 'inherit'}">${name}</span>
      <span class="li-stat">${stmts.length}건</span>
    </div>`;
    if (sorted.length === 0) {
      card.innerHTML += `<p class="li-empty">${gu} 관련 공식 발언·공약 없음</p>`;
    } else {
      sorted.forEach(s => card.appendChild(_buildStmtItem(s)));
    }
    officialGrid.appendChild(card);

    // 유튜브 카드
    if (ytStmts.length > 0) {
      hasYt = true;
      const ytCard = document.createElement('div');
      ytCard.className = 'local-insight-card li-yt-card';
      if (pc.border) ytCard.style.borderTopColor = pc.border;
      ytCard.innerHTML = `<div class="li-card-header">
        <span class="li-cand-name" style="color:${pc.label || 'inherit'}">${name}</span>
        <span class="li-stat">${ytStmts.length}건</span>
      </div>`;
      ytStmts.forEach(s => ytCard.appendChild(_buildStmtItem(s)));
      ytGrid.appendChild(ytCard);
    }
  });

  section.innerHTML = '';
  section.appendChild(header);
  section.appendChild(legend);
  section.appendChild(officialGrid);

  if (hasYt) {
    const ytHeader = document.createElement('div');
    ytHeader.className = 'li-yt-header';
    ytHeader.innerHTML = `<span>▶ 유튜브 캠페인 발언</span><span class="li-yt-notice">공식 공약이 아닌 캠페인 현장 발언입니다</span>`;
    section.appendChild(ytHeader);
    section.appendChild(ytGrid);
  }
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
  const hasProfile = Object.entries(state.profile).some(([k, v]) =>
    k !== 'freetext' && v && (Array.isArray(v) ? v.length > 0 : true)
  ) || (state.profile.freetext || '').trim().length > 0;

  const userImpact = (data.user_impact || '').trim();
  const impactBox = document.createElement('div');
  impactBox.className = 'user-impact-box';

  if (userImpact) {
    impactBox.innerHTML = `
      <div class="user-impact-label">내 상황에서 주목할 점</div>
      <p class="user-impact-text">${markdownBold(userImpact)}</p>
    `;
    container.appendChild(impactBox);
  } else if (hasProfile) {
    // user_impact 없지만 프로필 있음 → 별도 요청
    impactBox.innerHTML = `
      <div class="user-impact-label">내 상황에서 주목할 점</div>
      <p class="user-impact-text"><span class="mini-spinner"></span></p>
    `;
    container.appendChild(impactBox);
    fetch('/api/user-impact', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ topic, profile: state.profile }),
    }).then(r => r.json()).then(res => {
      const text = (res.user_impact || '').trim();
      if (text) {
        impactBox.querySelector('.user-impact-text').innerHTML = markdownBold(text);
        if (state.comparisons[topic]) state.comparisons[topic].user_impact = text;
      } else {
        impactBox.remove();
      }
    }).catch(() => impactBox.remove());
  }

  /* ── common_ground ── */
  const commonGround = (data.common_ground || '').trim();
  if (commonGround) {
    const cgBox = document.createElement('div');
    cgBox.className = 'common-ground-box';
    cgBox.innerHTML = `
      <div class="common-ground-label">세 후보가 동의하는 것</div>
      <p class="common-ground-text">${markdownBold(commonGround)}</p>
    `;
    container.appendChild(cgBox);
  }

  /* ── 1. 입장 차이 (key_diff 소제목 + clash) ── */
  const debateItems = data.debate || [];
  const clashSection = document.createElement('div');
  clashSection.className = 'subsection clash-section';

  const keyDiff = (data.key_diff || '').trim();
  const clashHeader = document.createElement('div');
  clashHeader.className = 'subsection-header';
  clashHeader.innerHTML = `
    <span class="subsection-label">입장 차이</span>
    <span class="ai-badge">AI 요약</span>
    <div class="subsection-actions">
      <button class="action-btn share-btn" title="결과 링크 공유">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/></svg>
        공유
      </button>
      <button class="action-btn snap-btn" title="이미지로 저장">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
        이미지
      </button>
    </div>
  `;
  clashHeader.querySelector('.share-btn').addEventListener('click', () => {
    const url = new URL(location.href);
    url.searchParams.set('topic', topic);
    const shareUrl = url.toString();
    if (navigator.share) {
      navigator.share({ title: `${topic} 후보 비교`, url: shareUrl }).catch(() => {});
    } else {
      navigator.clipboard.writeText(shareUrl).then(() => {
        const btn = clashHeader.querySelector('.share-btn');
        const orig = btn.innerHTML;
        btn.textContent = '복사됨 ✓';
        setTimeout(() => { btn.innerHTML = orig; }, 2000);
      });
    }
  });
  clashHeader.querySelector('.snap-btn').addEventListener('click', () => {
    // state.comparisons[topic]에서 최신 데이터(비동기 로드된 user_impact 포함) 사용
    const latest = state.comparisons[topic] || data;
    downloadSnapshot(topic, latest, window.location.href);
  });
  clashSection.appendChild(clashHeader);

  if (keyDiff) {
    const keyDiffTitle = document.createElement('p');
    keyDiffTitle.className = 'key-diff-subtitle';
    keyDiffTitle.textContent = keyDiff;
    clashSection.appendChild(keyDiffTitle);
  }

  // 후보별 입장 (3컬럼) — key_diff 바로 아래, 요약 박스 위
  const stanceGrid = document.createElement('div');
  stanceGrid.className = 'candidates-grid';
  (data.candidates || []).forEach(c => stanceGrid.appendChild(buildCandidateCard(c, topic, (data.sources || {})[c.name] || [])));
  clashSection.appendChild(stanceGrid);

  // 원문 근거 서랍 — 후보 카드와 입장 요약 사이
  const sources = data.sources || {};
  const hasAnySrc = Object.values(sources).some(arr => arr.length > 0);
  if (hasAnySrc) {
    clashSection.appendChild(buildSourceDrawer(sources));
  }

  const summary = data.clash_summary || '';
  if (summary && !summary.includes('충분하지 않')) {
    const p = document.createElement('p');
    p.className = 'clash-summary-text';
    p.innerHTML = markdownBold(summary);
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

  /* ── 4. 에이전트 채팅 패널 ── */
  container.appendChild(buildAgentPanel(topic));
}

/* ═══════════════════════════════════════════
   후보 카드
═══════════════════════════════════════════ */
function splitStanceText(text) {
  // 첫 문장 경계 탐색 (한국어 문장 종결: 다/요/음/임 + 마침표)
  const m = text.match(/^[\s\S]+?(?:[다요음임]\.|\.)\s+/);
  if (m && m[0].length < text.length - 10) {
    return [m[0].trimEnd(), text.slice(m[0].length).trimStart()];
  }
  // fallback: 80자 이상이면 어절 경계에서 자르기
  if (text.length > 90) {
    const cutAt = text.slice(0, 85).lastIndexOf(' ');
    if (cutAt > 40) return [text.slice(0, cutAt) + '…', text.slice(cutAt).trimStart()];
  }
  return [text, ''];
}

function buildCandidateCard(c, topic, candSources) {
  const card = document.createElement('div');
  card.className = 'candidate-card' + (c.has_data ? '' : ' no-data');
  const pc = PARTY_COLORS[c.party];
  if (pc && c.has_data) {
    card.style.borderLeftColor = pc.border;
    card.style.borderLeftWidth = '3px';
  }

  // stance 첫 문장 / 나머지 분리
  const fullStance = c.stance || '';
  const [preview, rest] = splitStanceText(fullStance);
  const hasMore = rest.length > 0;

  // stance_tag 스타일
  const tagStyle = (pc && c.has_data)
    ? `background:${pc.bg};color:${pc.label};border-color:${pc.border}55;`
    : '';

  card.innerHTML = `
    <div class="cand-header-row">
      <div>
        <div class="cand-name">${escapeHtml(c.name)}</div>
        <div class="cand-party" style="${pc && c.has_data ? `color:${pc.label};` : ''}">${escapeHtml(c.party)}</div>
      </div>
      ${c.stance_tag && c.has_data ? `<span class="stance-tag" style="${tagStyle}">${escapeHtml(c.stance_tag)}</span>` : ''}
    </div>
    <div class="cand-stance-wrap">
      <p class="cand-stance">
        <span class="stance-preview">${markdownBold(preview)}</span>${hasMore ? `<span class="stance-rest" hidden> ${markdownBold(rest)}</span>` : ''}
      </p>
      ${hasMore ? `<button class="stance-expand-btn" type="button">더 보기 ↓</button>` : ''}
    </div>
    ${c.has_data && topic ? `<button class="cand-ask-btn" data-name="${escapeHtml(c.name)}">이 후보에게 질문하기 →</button>` : ''}
  `;

  // 더 보기 토글
  if (hasMore) {
    const expandBtn = card.querySelector('.stance-expand-btn');
    const restEl = card.querySelector('.stance-rest');
    expandBtn.addEventListener('click', () => {
      const isOpen = !restEl.hidden;
      restEl.hidden = isOpen;
      expandBtn.textContent = isOpen ? '더 보기 ↓' : '접기 ↑';
    });
  }

  if (c.has_data && topic) {
    card.querySelector('.cand-ask-btn').addEventListener('click', () => {
      const panel = document.querySelector(`.agent-panel[data-topic="${CSS.escape(topic)}"]`);
      if (!panel) return;
      const chip = panel.querySelector(`.agent-target-chip[data-target="${c.name}"]`);
      if (chip) {
        panel.querySelectorAll('.agent-target-chip').forEach(ch => ch.classList.remove('selected'));
        chip.classList.add('selected');
      }
      panel.scrollIntoView({ behavior: 'smooth', block: 'center' });
      panel.querySelector('.agent-textarea')?.focus();
    });
  }

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
    <p class="debate-key-claim">${markdownBold(item.key_claim || '')}</p>
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
        <p class="rebuttal-text">${markdownBold(r.text || '')}</p>
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
  // URL 파라미터 초기화
  history.replaceState(null, '', location.pathname);
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

function markdownBold(str) {
  return escapeHtml(String(str)).replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
}

function stripBold(str) {
  return String(str).replace(/\*\*([^*]+)\*\*/g, '$1');
}

function truncate(str, max) {
  const s = stripBold(String(str || ''));
  return s.length > max ? s.slice(0, max).trimEnd() + '…' : s;
}

function buildTriangleSVG(data) {
  const W = 500, H = 310;
  const PCOLOR = { '더불어민주당': '#1D4ED8', '국민의힘': '#DC2626', '개혁신당': '#D97706' };
  const NW = 104, NH = 48;

  // 꼭짓점 위치: 정원오 위, 오세훈 오른쪽 아래, 김정철 왼쪽 아래
  const POS = { '정원오': [250, 58], '오세훈': [434, 258], '김정철': [66, 258] };

  // debate 데이터에서 화살표 추출: { from, to, angle, color }
  const arrows = [];
  const candParty = {};
  (data.candidates || []).forEach(c => { candParty[c.name] = c.party; });
  (data.debate || []).forEach(item => {
    (item.rebuttals || []).forEach(r => {
      if (!POS[r.from] || !POS[item.candidate]) return;
      arrows.push({
        from: r.from, to: item.candidate,
        angle: r.angle || '',
        color: PCOLOR[candParty[r.from]] || '#888',
      });
    });
  });

  // 쌍별 인덱스 부여 (양방향 화살표 오프셋용)
  const pairCount = {};
  arrows.forEach(a => {
    const k = [a.from, a.to].sort().join('|');
    pairCount[k] = (pairCount[k] || 0) + 1;
  });
  const pairRun = {};
  arrows.forEach(a => {
    const k = [a.from, a.to].sort().join('|');
    pairRun[k] = pairRun[k] || 0;
    a._idx   = pairRun[k]++;
    a._total = pairCount[k];
  });

  const parts = [];

  // ── 마커 정의 ──
  const uniqColors = [...new Set(arrows.map(a => a.color))];
  parts.push('<defs>');
  uniqColors.forEach((c, i) => {
    parts.push(`<marker id="ah${i}" markerWidth="9" markerHeight="7"
      refX="8" refY="3.5" orient="auto">
      <path d="M0,0 L9,3.5 L0,7 Z" fill="${c}"/>
    </marker>`);
  });
  parts.push('</defs>');

  // ── 배경 삼각형 ──
  const [p1, p2, p3] = [POS['정원오'], POS['오세훈'], POS['김정철']];
  parts.push(`<polygon points="${p1} ${p2} ${p3}"
    fill="#f1f5f9" stroke="#cbd5e1" stroke-width="1" stroke-dasharray="5 3"/>`);

  // ── 화살표 ──
  arrows.forEach(a => {
    const [fx, fy] = POS[a.from];
    const [tx, ty] = POS[a.to];
    const cidx = uniqColors.indexOf(a.color);

    const ddx = tx - fx, ddy = ty - fy;
    const len = Math.sqrt(ddx*ddx + ddy*ddy);
    const nx = ddx/len, ny = ddy/len;
    const px = -ny, py = nx;

    const sideOff = a._total > 1 ? (a._idx === 0 ? -24 : 24) : 0;
    const curve   = a._total > 1 ? 28 : 14;
    const dir     = a._idx === 0 ? 1 : -1;

    const sx = fx + nx * (NW/2 + 2) + px * sideOff;
    const sy = fy + ny * (NH/2 + 2) + py * sideOff;
    const ex = tx - nx * (NW/2 + 10) + px * sideOff;
    const ey = ty - ny * (NH/2 + 2) + py * sideOff;

    const mx = (sx+ex)/2 + px * (sideOff*0.4 + curve*dir);
    const my = (sy+ey)/2 + py * (sideOff*0.4 + curve*dir);

    // 레이블 위치 (베지어 t=0.5)
    const lx = Math.round(0.25*sx + 0.5*mx + 0.25*ex);
    const ly = Math.round(0.25*sy + 0.5*my + 0.25*ey);
    const pillW = Math.max(52, a.angle.length * 8.5 + 14);

    parts.push(`<path d="M${sx.toFixed(1)},${sy.toFixed(1)} Q${mx.toFixed(1)},${my.toFixed(1)} ${ex.toFixed(1)},${ey.toFixed(1)}"
      fill="none" stroke="${a.color}" stroke-width="1.8" stroke-opacity="0.7"
      marker-end="url(#ah${cidx})"/>`);
    parts.push(`<rect x="${lx - pillW/2}" y="${ly - 11}" width="${pillW}" height="22" rx="11"
      fill="${a.color}" fill-opacity="0.13" stroke="${a.color}" stroke-opacity="0.4" stroke-width="1"/>`);
    parts.push(`<text x="${lx}" y="${ly + 5}" text-anchor="middle"
      font-family="Pretendard,-apple-system,sans-serif" font-size="10.5" font-weight="700"
      fill="${a.color}">${escapeHtml(a.angle)}</text>`);
  });

  // ── 노드 (화살표 위에 그려서 내부 화살표 가림) ──
  (data.candidates || []).forEach(c => {
    if (!POS[c.name]) return;
    const [cx, cy] = POS[c.name];
    const col = PCOLOR[c.party] || '#888';
    parts.push(`<rect x="${cx-NW/2}" y="${cy-NH/2}" width="${NW}" height="${NH}" rx="11"
      fill="white" stroke="${col}" stroke-width="2.5"/>`);
    parts.push(`<text x="${cx}" y="${cy-4}" text-anchor="middle"
      font-family="Pretendard,-apple-system,sans-serif" font-size="16" font-weight="800"
      fill="${col}">${escapeHtml(c.name)}</text>`);
    parts.push(`<text x="${cx}" y="${cy+15}" text-anchor="middle"
      font-family="Pretendard,-apple-system,sans-serif" font-size="10" font-weight="500"
      fill="${col}" opacity="0.7">${escapeHtml(c.party)}</text>`);
  });

  return `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg">${parts.join('')}</svg>`;
}

function buildTriangleSVGv2(data) {
  // ── 캔버스 & 상수 ──
  const W = 600, H = 420;
  const PCOLOR = { '더불어민주당': '#1D4ED8', '국민의힘': '#DC2626', '개혁신당': '#D97706' };
  const NW = 116, NH = 54;
  // 후보 노드 위치: 정원오 위, 오세훈 오른쪽 아래, 김정철 왼쪽 아래
  const POS = { '정원오': [300, 72], '오세훈': [520, 348], '김정철': [80, 348] };

  const candParty = {};
  (data.candidates || []).forEach(c => { candParty[c.name] = c.party; });

  // debate → 화살표 목록 (from → to, 반박 각도)
  const arrows = [];
  (data.debate || []).forEach(item => {
    (item.rebuttals || []).forEach(r => {
      if (!POS[r.from] || !POS[item.candidate]) return;
      arrows.push({
        from:  r.from,
        to:    item.candidate,
        angle: r.angle || '',
        color: PCOLOR[candParty[r.from]] || '#888',
      });
    });
  });

  // 같은 쌍의 화살표 인덱스 (양방향 오프셋 분리)
  const pairCount = {}, pairRun = {};
  arrows.forEach(a => {
    const k = [a.from, a.to].sort().join('|');
    pairCount[k] = (pairCount[k] || 0) + 1;
  });
  arrows.forEach(a => {
    const k = [a.from, a.to].sort().join('|');
    pairRun[k] = pairRun[k] || 0;
    a._idx   = pairRun[k]++;
    a._total = pairCount[k];
  });

  const parts = [];
  const uniqColors = [...new Set(arrows.map(a => a.color))];

  // ── 마커 (화살촉) ──
  parts.push('<defs>');
  uniqColors.forEach((c, i) => {
    parts.push(`<marker id="arh_${i}" markerWidth="8" markerHeight="6"
      refX="7" refY="3" orient="auto">
      <path d="M0,0 L8,3 L0,6 Z" fill="${c}"/>
    </marker>`);
  });
  parts.push('</defs>');

  // ── 배경 삼각형 ──
  const [p1, p2, p3] = [POS['정원오'], POS['오세훈'], POS['김정철']];
  parts.push(`<polygon points="${p1[0]},${p1[1]} ${p2[0]},${p2[1]} ${p3[0]},${p3[1]}"
    fill="#f8faff" stroke="#d1d9f0" stroke-width="1.5" stroke-dasharray="6 4"/>`);

  // ── 화살표 + 레이블 ──
  arrows.forEach(a => {
    const [fx, fy] = POS[a.from];
    const [tx, ty] = POS[a.to];
    const cidx = uniqColors.indexOf(a.color);

    const ddx = tx - fx, ddy = ty - fy;
    const len = Math.sqrt(ddx * ddx + ddy * ddy);
    const nx = ddx / len, ny = ddy / len;   // 방향 단위벡터
    const px = -ny, py = nx;                // 수직 단위벡터

    // 양방향 쌍: 서로 옆으로 분리
    const sideOff = a._total > 1 ? (a._idx === 0 ? -20 : 20) : 0;

    // 화살표 시작: 소스 노드 엣지에서 출발
    const sx = fx + nx * (NW / 2 + 6) + px * sideOff;
    const sy = fy + ny * (NH / 2 + 6) + py * sideOff;
    // 화살표 끝: 목적지 노드 바로 앞 (완전히 닿게)
    const ex = tx - nx * (NW / 2 + 10) + px * sideOff;
    const ey = ty - ny * (NH / 2 + 6)  + py * sideOff;

    // 화살표 경로 (곡선으로 양방향 분리 강조)
    const curvePull = a._total > 1 ? (a._idx === 0 ? -30 : 30) : 0;
    const cpx = (sx + ex) / 2 + px * curvePull;
    const cpy = (sy + ey) / 2 + py * curvePull;

    parts.push(`<path d="M${sx.toFixed(1)},${sy.toFixed(1)} Q${cpx.toFixed(1)},${cpy.toFixed(1)} ${ex.toFixed(1)},${ey.toFixed(1)}"
      fill="none" stroke="${a.color}" stroke-width="2" stroke-opacity="0.75"
      marker-end="url(#arh_${cidx})"/>`);

    // 레이블: 베지어 t=0.5 지점, 화살표 수직 방향으로 offset
    const lx = Math.round(0.25 * sx + 0.5 * cpx + 0.25 * ex);
    const ly = Math.round(0.25 * sy + 0.5 * cpy + 0.25 * ey);
    const labelOffDir = a._total > 1 ? (a._idx === 0 ? -1 : 1) : (px > 0 ? 1 : -1);
    const LABEL_OFF = 28;
    const lbx = lx + px * labelOffDir * LABEL_OFF;
    const lby = ly + py * labelOffDir * LABEL_OFF;

    // 배지: 반박 각도 텍스트
    const bw = Math.max(60, a.angle.length * 8 + 16);
    const bh = 22;
    parts.push(`<rect x="${(lbx - bw/2).toFixed(1)}" y="${(lby - bh/2).toFixed(1)}"
      width="${bw}" height="${bh}" rx="${bh/2}"
      fill="${a.color}" fill-opacity="0.14"
      stroke="${a.color}" stroke-width="1.4"/>`);
    parts.push(`<text x="${lbx.toFixed(1)}" y="${(lby + 5).toFixed(1)}" text-anchor="middle"
      font-family="Pretendard,-apple-system,sans-serif"
      font-size="10.5" font-weight="800" fill="${a.color}">${escapeHtml(a.angle)}</text>`);
  });

  // ── 후보 노드 (화살표 위에 그려 끝단 가림) ──
  (data.candidates || []).forEach(c => {
    if (!POS[c.name]) return;
    const [cx, cy] = POS[c.name];
    const col = PCOLOR[c.party] || '#888';
    // 그림자
    parts.push(`<rect x="${cx - NW/2 + 2}" y="${cy - NH/2 + 3}"
      width="${NW}" height="${NH}" rx="13" fill="rgba(0,0,0,0.08)"/>`);
    // 흰 배경
    parts.push(`<rect x="${cx - NW/2}" y="${cy - NH/2}"
      width="${NW}" height="${NH}" rx="13"
      fill="white" stroke="${col}" stroke-width="2.5"/>`);
    // 이름
    parts.push(`<text x="${cx}" y="${cy - 3}" text-anchor="middle"
      font-family="Pretendard,-apple-system,sans-serif"
      font-size="18" font-weight="800" fill="${col}">${escapeHtml(c.name)}</text>`);
    // 정당
    parts.push(`<text x="${cx}" y="${cy + 17}" text-anchor="middle"
      font-family="Pretendard,-apple-system,sans-serif"
      font-size="11" font-weight="500" fill="${col}" opacity="0.7">${escapeHtml(c.party)}</text>`);
  });

  return `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}"
    xmlns="http://www.w3.org/2000/svg" style="overflow:visible">${parts.join('')}</svg>`;
}

/* ═══════════════════════════════════════════════════════════════
   Canvas 기반 스냅샷 — 9:16 고정 (540×960), Retina ×2
═══════════════════════════════════════════════════════════════ */
const SNAP_W = 540, SNAP_H = 960, SNAP_SCALE = 2;
const SNAP_FONT = 'Pretendard,"Apple SD Gothic Neo","Malgun Gothic",system-ui,sans-serif';
const SNAP_PC   = { '더불어민주당': '#1D4ED8', '국민의힘': '#DC2626', '개혁신당': '#D97706' };
const SNAP_PBG  = { '더불어민주당': '#eff6ff',  '국민의힘': '#fef2f2',  '개혁신당': '#fffbeb' };
const SNAP_PT   = { '더불어민주당': '#1e3a8a',  '국민의힘': '#7f1d1d',  '개혁신당': '#78350f' };

function _snapRR(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x+r, y);
  ctx.lineTo(x+w-r, y); ctx.quadraticCurveTo(x+w, y, x+w, y+r);
  ctx.lineTo(x+w, y+h-r); ctx.quadraticCurveTo(x+w, y+h, x+w-r, y+h);
  ctx.lineTo(x+r, y+h); ctx.quadraticCurveTo(x, y+h, x, y+h-r);
  ctx.lineTo(x, y+r); ctx.quadraticCurveTo(x, y, x+r, y);
  ctx.closePath();
}

// 한국어 포함 텍스트 줄바꿈. 반환값: 실제 줄 수
function _snapWrap(ctx, text, x, y, maxW, lineH, maxLines=99) {
  // 공백 기준으로 분리하되 단어가 maxW를 넘으면 글자 단위 분리
  const words = text.split(/(\s+)/);
  let line = '', lines = [];
  for (const w of words) {
    if (/^\s+$/.test(w)) { line += w; continue; }
    const test = line + w;
    if (ctx.measureText(test).width > maxW && line.trim()) {
      lines.push(line.trimEnd());
      if (lines.length >= maxLines) break;
      line = w;
    } else { line = test; }
  }
  if (line.trim() && lines.length < maxLines) lines.push(line.trim());
  if (lines.length === maxLines) {
    const last = lines[maxLines-1];
    if (ctx.measureText(last+'…').width < maxW) lines[maxLines-1] = last + '…';
    else lines[maxLines-1] = last.slice(0,-1) + '…';
  }
  lines.forEach((l, i) => ctx.fillText(l, x, y + i * lineH));
  return lines.length;
}

function _snapArrow(ctx, x1, y1, x2, y2, color) {
  const ang = Math.atan2(y2-y1, x2-x1);
  const hs  = 7;
  ctx.beginPath(); ctx.moveTo(x1,y1); ctx.lineTo(x2,y2);
  ctx.strokeStyle = color; ctx.lineWidth = 1.5; ctx.stroke();
  ctx.beginPath(); ctx.moveTo(x2, y2);
  ctx.lineTo(x2-hs*Math.cos(ang-0.38), y2-hs*Math.sin(ang-0.38));
  ctx.lineTo(x2-hs*Math.cos(ang+0.38), y2-hs*Math.sin(ang+0.38));
  ctx.closePath(); ctx.fillStyle = color; ctx.fill();
}

// 상호 비판 구도 — 카드 리스트 형식
function _snapDebateList(ctx, enrichedData, ax, ay, aw, maxH) {
  const candMap = {};
  (enrichedData.candidates||[]).forEach(c => { candMap[c.name] = c; });

  const rows = [];
  (enrichedData.debate||[]).forEach(item => {
    const toC = candMap[item.candidate];
    (item.rebuttals||[]).forEach(r => {
      const fromC = candMap[r.from];
      rows.push({
        from:      r.from,
        fromColor: SNAP_PC[fromC?.party]||'#888',
        fromBg:    SNAP_PBG[fromC?.party]||'#f5f5f5',
        to:        item.candidate,
        toColor:   SNAP_PC[toC?.party]||'#888',
        angle:     r.angle||'',
        text:      (r.text_short||'').trim(),
      });
    });
  });

  const LINE_H = 14;
  let y = ay;

  for (const row of rows) {
    const hasText = row.text.length > 0;
    // 텍스트 줄 수 미리 계산 (최대 3줄)
    let textLines = 0;
    if (hasText) {
      ctx.font = `400 10.5px ${SNAP_FONT}`;
      const words = row.text.split(/(\s+)/);
      let ln='', cnt=0;
      for (const w of words) {
        if (/^\s+$/.test(w)) { ln+=w; continue; }
        const t = ln+w;
        if (ctx.measureText(t).width > aw-26 && ln.trim()) { cnt++; ln=w; if(cnt>=3) break; }
        else ln=t;
      }
      if (ln.trim() && cnt<3) cnt++;
      textLines = Math.min(cnt, 3);
    }
    const CARD_H = 22 + (hasText ? 8 + textLines*LINE_H : 0) + 8;

    if (y + CARD_H > ay + maxH - 2) break;

    // 카드 배경 + 왼쪽 컬러 바
    ctx.fillStyle = '#ffffff';
    _snapRR(ctx, ax, y, aw, CARD_H, 8); ctx.fill();
    ctx.fillStyle = row.fromColor;
    _snapRR(ctx, ax, y, 3, CARD_H, 4); ctx.fill();

    // from → to 헤더
    let hx = ax + 12;
    const hy = y + 16;
    ctx.fillStyle = row.fromColor; ctx.font = `800 11px ${SNAP_FONT}`;
    ctx.fillText(row.from, hx, hy);
    hx += ctx.measureText(row.from).width + 5;

    ctx.fillStyle = '#94a3b8'; ctx.font = `400 10px ${SNAP_FONT}`;
    ctx.fillText('→', hx, hy);
    hx += ctx.measureText('→').width + 5;

    ctx.fillStyle = row.toColor; ctx.font = `800 11px ${SNAP_FONT}`;
    ctx.fillText(row.to, hx, hy);
    hx += ctx.measureText(row.to).width + 9;

    // angle 배지
    if (row.angle) {
      ctx.font = `700 9px ${SNAP_FONT}`;
      const bw = ctx.measureText(row.angle).width;
      ctx.fillStyle = row.fromBg;
      _snapRR(ctx, hx-3, y+6, bw+8, 14, 7); ctx.fill();
      ctx.strokeStyle = row.fromColor+'55'; ctx.lineWidth = 1;
      _snapRR(ctx, hx-3, y+6, bw+8, 14, 7); ctx.stroke();
      ctx.fillStyle = row.fromColor;
      ctx.fillText(row.angle, hx, hy);
    }

    // 비판 근거 텍스트 (3줄 wrap)
    if (hasText) {
      ctx.fillStyle = '#475569';
      ctx.font = `400 10.5px ${SNAP_FONT}`;
      _snapWrap(ctx, row.text, ax+12, y+30, aw-26, LINE_H, 3);
    }

    y += CARD_H + 5;
  }
}

async function downloadSnapshot(topic, data, pageUrl) {
  const snapBtns = document.querySelectorAll(`.snap-btn, .btn-snapshot[data-snap="${CSS.escape(topic)}"]`);
  const origLabels = [];
  snapBtns.forEach(b => {
    origLabels.push(b.innerHTML);
    b.disabled = true;
    b.innerHTML = '<span style="font-size:11px">요약 중…</span>';
  });

  try {
    await document.fonts.ready;

    // ── 이미지용 텍스트 요약 API 호출 ──────────────────
    let summary = null;
    try {
      const res = await fetch('/api/image-summary', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ data }),
      });
      if (res.ok) summary = await res.json();
    } catch(e) { console.warn('[snapshot] summary API 실패, 원본 텍스트 사용:', e); }

    // summary로 data 보강
    const getSum = (name) => (summary?.candidates||[]).find(s => s.name === name);
    const getDebateSum = (from, to) => (summary?.debate||[]).find(d => d.from===from && d.to===to);

    // user_impact: API 요약 우선, 실패 시 원본을 70자로 자름
    const rawImpact = stripBold((data.user_impact||'').trim());
    const userImpactText = summary?.user_impact_short || (rawImpact.length > 70 ? rawImpact.slice(0,68)+'…' : rawImpact);

    // debate에 text_short 주입 (API 실패 시 원본 text 첫 문장 40자 fallback)
    const enrichedDebate = (data.debate||[]).map(item => ({
      ...item,
      rebuttals: (item.rebuttals||[]).map(r => {
        const ds = getDebateSum(r.from, item.candidate);
        if (ds) return { ...r, text_short: ds.text_short };
        const fb = stripBold(r.text||'');
        const sent = fb.split(/(?<=[.!?다])\s/)[0] || fb;
        return { ...r, text_short: sent.length > 45 ? sent.slice(0,43)+'…' : sent };
      }),
    }));
    const enrichedData = { ...data, debate: enrichedDebate };

    // ── Canvas 그리기 ───────────────────────────────────
    const cv = document.createElement('canvas');
    cv.width  = SNAP_W * SNAP_SCALE;
    cv.height = SNAP_H * SNAP_SCALE;
    const ctx = cv.getContext('2d');
    ctx.scale(SNAP_SCALE, SNAP_SCALE);
    ctx.textBaseline = 'alphabetic';

    ctx.fillStyle = '#f8fafc';
    ctx.fillRect(0, 0, SNAP_W, SNAP_H);

    // ① 헤더
    const HDR_H = 148;
    const grad = ctx.createLinearGradient(0,0,SNAP_W,HDR_H);
    grad.addColorStop(0,'#0f172a'); grad.addColorStop(1,'#1e3a5f');
    ctx.fillStyle = grad; ctx.fillRect(0,0,SNAP_W,HDR_H);

    ctx.fillStyle='rgba(255,255,255,0.38)'; ctx.font=`700 9px ${SNAP_FONT}`;
    ctx.fillText('2026 서울시장 선거', 32, 36);

    const fsTopic = topic.length > 8 ? 26 : topic.length > 5 ? 30 : 34;
    ctx.fillStyle='#fff'; ctx.font=`800 ${fsTopic}px ${SNAP_FONT}`;
    ctx.fillText(topic, 32, 82);

    const keyDiff = stripBold(data.key_diff||'');
    ctx.fillStyle='rgba(255,255,255,0.52)'; ctx.font=`400 11px ${SNAP_FONT}`;
    _snapWrap(ctx, keyDiff, 32, 108, SNAP_W-64, 15, 2);

    let y = HDR_H + 10;

    // ② 내 상황
    if (userImpactText) {
      const LPAD = 30, RPAD = 30, LINE_H = 15;
      ctx.font=`400 11px ${SNAP_FONT}`;
      // 실제 줄 수 계산 (최대 3줄)
      const words2 = userImpactText.split(/(\s+)/);
      let line2='', lineCount=0;
      for (const w of words2) {
        if (/^\s+$/.test(w)) { line2+=w; continue; }
        const t = line2+w;
        if (ctx.measureText(t).width > SNAP_W-LPAD-RPAD && line2.trim()) { lineCount++; line2=w; if(lineCount>=3) break; }
        else line2=t;
      }
      if (line2.trim() && lineCount<3) lineCount++;
      lineCount = Math.min(lineCount, 3);
      const BOX_H = 13 + lineCount*LINE_H + 11;
      ctx.fillStyle='#fefce8'; _snapRR(ctx,20,y,SNAP_W-40,BOX_H,10); ctx.fill();
      ctx.strokeStyle='#fde68a'; ctx.lineWidth=1.5; _snapRR(ctx,20,y,SNAP_W-40,BOX_H,10); ctx.stroke();
      ctx.fillStyle='#b45309'; ctx.font=`700 9px ${SNAP_FONT}`;
      ctx.fillText('💡 내 상황에서 주목할 점', LPAD, y+12);
      ctx.fillStyle='#78350f'; ctx.font=`400 11px ${SNAP_FONT}`;
      _snapWrap(ctx, userImpactText, LPAD, y+27, SNAP_W-LPAD-RPAD, LINE_H, 3);
      y += BOX_H + 8;
    }

    // ③ 후보별 입장
    ctx.fillStyle='#94a3b8'; ctx.font=`700 9px ${SNAP_FONT}`;
    ctx.fillText('후보별 핵심 입장', 20, y+9); y+=17;

    const STANCE_H = 72;
    (data.candidates||[]).slice(0,3).forEach(c => {
      const color  = SNAP_PC[c.party]||'#888';
      const tcolor = SNAP_PT[c.party]||'#111';
      const sc = getSum(c.name);
      ctx.fillStyle='#fff'; _snapRR(ctx,20,y,SNAP_W-40,STANCE_H,8); ctx.fill();
      ctx.fillStyle=color; _snapRR(ctx,20,y,4,STANCE_H,4); ctx.fill();

      ctx.fillStyle=color; ctx.font=`800 13px ${SNAP_FONT}`;
      ctx.fillText(c.name, 34, y+17);
      const nw = ctx.measureText(c.name).width;
      ctx.font=`500 10px ${SNAP_FONT}`;
      ctx.fillText(c.party, 34+nw+7, y+16);

      // stance_short: 요약 API 결과 우선, 1줄 wrap
      const short = (sc?.stance_short || c.stance_short || (c.has_data?'':'공식 입장 없음'));
      if (short) {
        ctx.fillStyle=tcolor; ctx.font=`600 11px ${SNAP_FONT}`;
        _snapWrap(ctx, short, 34, y+33, SNAP_W-60, 14, 1);
      }
      // stance_detail: API 요약 결과만 표시
      const detail = sc?.stance_detail || '';
      if (detail) {
        ctx.fillStyle='#94a3b8'; ctx.font=`400 10px ${SNAP_FONT}`;
        _snapWrap(ctx, detail, 34, y+48, SNAP_W-60, 12, 2);
      }
      y += STANCE_H+5;
    });

    y += 6;

    // ④ 상호 비판 구도
    ctx.fillStyle='#94a3b8'; ctx.font=`700 9px ${SNAP_FONT}`;
    ctx.fillText('상호 비판 구도', 20, y+9); y+=16;

    const listH = SNAP_H - 56 - y;
    _snapDebateList(ctx, enrichedData, 20, y, SNAP_W-40, listH);

    // ⑤ 푸터 (2줄)
    ctx.fillStyle='#e2e8f0'; ctx.fillRect(0,SNAP_H-56,SNAP_W,56);

    // 윗줄: 출처 | 날짜
    ctx.fillStyle='#94a3b8'; ctx.font=`400 10px ${SNAP_FONT}`;
    ctx.fillText('공식 입장 기반 · AI 요약', 20, SNAP_H-34);
    ctx.textAlign='right';
    ctx.fillText('2026.6.4 지방선거', SNAP_W-20, SNAP_H-34);
    ctx.textAlign='left';

    // 아랫줄: 페이지 URL
    if (pageUrl) {
      const shortUrl = pageUrl.replace(/^https?:\/\//, '');
      ctx.fillStyle='#60a5fa'; ctx.font=`400 9px ${SNAP_FONT}`;
      ctx.textAlign='center';
      ctx.fillText('🔗 ' + shortUrl, SNAP_W/2, SNAP_H-14);
      ctx.textAlign='left';
    }

    const link = document.createElement('a');
    link.download = `서울시장_${topic}_정책비교.png`;
    link.href = cv.toDataURL('image/png');
    link.click();

  } catch(e) {
    console.error('[snapshot] 오류:', e);
    alert(`이미지 생성 오류: ${e.message}`);
  } finally {
    snapBtns.forEach((b, i) => { b.disabled = false; b.innerHTML = origLabels[i]; });
  }
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

      cardMap[name].querySelector('.chat-answer-text').innerHTML = markdownBold(answer);
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
