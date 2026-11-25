(function () {
  var sb = document.getElementById('sidebar'), sc = document.getElementById('scrim'), mb = document.getElementById('menuBtn');
  function toggle() { if (!sb) return; sb.classList.toggle('open'); sc.classList.toggle('open'); }
  if (mb) mb.addEventListener('click', toggle);
  if (sc) sc.addEventListener('click', toggle);

  // auto-hide toasts
  document.querySelectorAll('.toast').forEach(function (t) {
    setTimeout(function () { t.style.opacity = '0'; t.style.transition = '.4s'; setTimeout(function () { t.remove(); }, 400); }, 6500);
    var b = t.querySelector('button'); if (b) b.addEventListener('click', function () { t.remove(); });
  });

  // confirm dialogs on destructive buttons
  document.querySelectorAll('[data-confirm]').forEach(function (el) {
    el.addEventListener('click', function (e) { if (!confirm(el.getAttribute('data-confirm'))) e.preventDefault(); });
  });

  // dynamic prescription rows
  var addBtn = document.getElementById('addRx');
  if (addBtn) {
    var total = document.getElementById('id_items-TOTAL_FORMS');
    var tpl = document.getElementById('rxTemplate');
    var wrap = document.getElementById('rxRows');
    addBtn.addEventListener('click', function () {
      var idx = parseInt(total.value, 10);
      var html = tpl.innerHTML.replace(/__prefix__/g, idx);
      var div = document.createElement('div');
      div.innerHTML = html.trim();
      wrap.appendChild(div.firstElementChild);
      total.value = idx + 1;
      bindRemove();
      wrap.lastElementChild.querySelector('input[type=text]').focus();
    });
    function bindRemove() {
      wrap.querySelectorAll('.rm').forEach(function (b) {
        if (b.dataset.bound) return; b.dataset.bound = 1;
        b.addEventListener('click', function () {
          var row = b.closest('.rx-row');
          var del = row.querySelector('input[type=checkbox][name$="-DELETE"]');
          if (del) { del.checked = true; row.classList.add('deleted'); }
          else { row.remove(); }
        });
      });
    }
    bindRemove();
  }

  // auto print
  if (location.search.indexOf('auto=1') > -1 && document.body.classList.contains('print-page')) {
    window.addEventListener('load', function () { setTimeout(function () { window.print(); }, 400); });
  }

  // image preview for file inputs
  document.querySelectorAll('input[type=file][accept^="image"]').forEach(function (inp) {
    inp.addEventListener('change', function () {
      var f = inp.files[0]; if (!f) return;
      var box = document.getElementById('photoPreview'); if (!box) return;
      var r = new FileReader(); r.onload = function (e) { box.innerHTML = '<img src="' + e.target.result + '" alt="">'; box.classList.remove('initials'); };
      r.readAsDataURL(f);
    });
  });
})();
