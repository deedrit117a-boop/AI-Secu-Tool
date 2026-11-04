// ---------- 접근성 보강
// 화면이 innerHTML 로 자주 다시 그려지므로, 그려질 때마다 (변경 감지 후) 키보드/스크린리더용 속성을 일괄로 붙인다.
// - 클릭만 되는 div/span 을 키보드(Tab, Enter, Space)로 쓸 수 있게 한다
// - 이름이 없는 입력칸/아이콘 버튼에 이름을 붙이고, 표 머리글에 scope 를 붙인다
// - 경고 상자는 스크린리더가 알려주도록 role 을 붙인다
(function(){
  const CLICKABLE='#sgl [data-n], .tab, [onclick]:not(button):not(a):not(input):not(select):not(textarea):not(summary):not(label)';
  const NATIVE='button,a[href],input,select,textarea,summary,[tabindex]';
  function enhance(root){
    root.querySelectorAll(CLICKABLE).forEach(el=>{
      if(el.matches(NATIVE)||el.dataset.a11y)return;
      el.dataset.a11y='1';el.tabIndex=0;el.setAttribute('role',el.classList.contains('tab')?'tab':'button');
      if(el.classList.contains('tab'))el.setAttribute('aria-selected',el.classList.contains('on')?'true':'false');
    });
    // 이름 없는 입력칸: placeholder → title → 같은 칸의 라벨(.hlabel) 순서로 이름을 붙인다
    root.querySelectorAll('input:not([type=hidden]):not([type=checkbox]):not([type=radio]):not([aria-label]):not([aria-labelledby]),textarea:not([aria-label]),select:not([aria-label])').forEach(el=>{
      if(el.closest('label')||(el.id&&document.querySelector(`label[for="${CSS.escape(el.id)}"]`)))return;
      const nm=el.getAttribute('placeholder')||el.title||(el.parentElement&&el.parentElement.querySelector(':scope > .hlabel')||{}).textContent||'';
      if(nm.trim())el.setAttribute('aria-label',nm.trim());
    });
    root.querySelectorAll('input[type=checkbox]:not([aria-label]),input[type=radio]:not([aria-label])').forEach(el=>{
      if(el.closest('label')||(el.id&&document.querySelector(`label[for="${CSS.escape(el.id)}"]`)))return;
      if(el.title)el.setAttribute('aria-label',el.title);
    });
    root.querySelectorAll('button:not([aria-label])').forEach(b=>{
      if(!b.textContent.trim()&&b.title)b.setAttribute('aria-label',b.title);
    });
    root.querySelectorAll('th:not([scope])').forEach(th=>th.setAttribute('scope','col'));
    root.querySelectorAll('.warnbox.danger:not([role])').forEach(w=>w.setAttribute('role','alert'));
    root.querySelectorAll('.warnbox:not(.danger):not([role])').forEach(w=>w.setAttribute('role','status'));
  }
  let pending=false;
  const schedule=()=>{if(pending)return;pending=true;requestAnimationFrame(()=>{pending=false;enhance(document.body)})};
  document.addEventListener('DOMContentLoaded',()=>{enhance(document.body);new MutationObserver(schedule).observe(document.body,{childList:true,subtree:true})});
  // Enter / Space 로 클릭 (위에서 키보드 대상으로 만든 요소만)
  document.addEventListener('keydown',e=>{
    const el=e.target;if(!el||!el.dataset||!el.dataset.a11y)return;
    if(e.key==='Enter'||e.key===' '){e.preventDefault();el.click()}
  });
  window.a11yEnhance=()=>enhance(document.body);
})();
