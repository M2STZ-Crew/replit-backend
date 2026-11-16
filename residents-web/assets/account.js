// RepLiT's residents' site (v1.12.35): delete an account, or restore it within
// its 30 days, without the app. The server checks the email and password each
// time (POST /auth/delete, /auth/restore); nothing is kept in this browser but
// the language chosen.
(function () {
  'use strict';

  var API = 'https://replit-backend-2li4.onrender.com';
  // A sleeping server can take most of a minute to answer the first request.
  var TIMEOUT_MS = 75000;

  var TEXT = {
    en: {
      brandSub: 'For residents of Barangay 76',
      kicker: 'For residents',
      title: 'Delete your RepLiT account',
      lede: 'Your account is frozen for 30 days first. In those 30 days you can still restore it; after them it is deleted for good.',
      whatHappens: 'What happens',
      step1Title: 'Right away',
      step1: 'You are signed out on every phone, and RepLiT stops sending you alerts.',
      step2Title: 'For 30 days',
      step2: 'Your account is kept, frozen. To keep it, sign in to the app and choose Restore my account, or use Restore your account below.',
      step3Title: 'After 30 days',
      step3: 'Your sign-in and profile (name, email, mobile number, birthday, gender, language and last location), your alerts and any National ID photos are deleted for good.',
      step4Title: 'What stays',
      step4: "The reports you sent stay in the barangay's incident records, without your name.",
      staffNote: "Staff accounts (coordinators and responders) are removed by their organization's administrator.",
      deleteHeading: 'Delete my account',
      email: 'Email',
      password: 'Password',
      show: 'Show',
      hide: 'Hide',
      tick: 'I understand that my account is frozen now and deleted for good after 30 days unless I restore it.',
      deleteBtn: 'Delete my account',
      working: 'Working…',
      needBoth: 'Enter the email and password of your RepLiT account.',
      needTick: 'Tick the box to confirm.',
      deleted: 'Your account is frozen. It will be deleted for good on {date}. To keep it, restore it before then.',
      restoreHeading: 'Changed your mind? Restore your account',
      restoreLede: 'Within 30 days of asking to delete it, your account comes back exactly as it was.',
      restoreBtn: 'Restore my account',
      restored: 'Your account is restored. You can sign in to the app as usual.',
      wrong: 'Wrong email or password.',
      staff: "This is a staff account. Your organization's administrator removes it.",
      notScheduled: 'This account is not set to be deleted. You can sign in as usual.',
      unavailable: 'Deleting or restoring an account is not available just now. Try again later.',
      offline: 'Could not reach RepLiT. Check your internet connection and try again. It can take up to a minute to wake.',
      generic: 'Something went wrong. Try again in a minute.',
      home: 'RepLiT for residents',
      privacyLink: 'Privacy policy'
    },
    tl: {
      brandSub: 'Para sa mga residente ng Barangay 76',
      kicker: 'Para sa mga residente',
      title: 'Burahin ang RepLiT account mo',
      lede: 'Ifi-freeze muna ang account mo nang 30 araw. Sa loob ng 30 araw na iyon, puwede mo pa itong ibalik; pagkatapos noon, buburahin na ito nang tuluyan.',
      whatHappens: 'Ano ang mangyayari',
      step1Title: 'Agad-agad',
      step1: 'Masa-sign out ka sa lahat ng phone, at hihinto ang mga alerto ng RepLiT sa iyo.',
      step2Title: 'Sa loob ng 30 araw',
      step2: 'Nakatago at naka-freeze ang account mo. Para manatili ito, mag-sign in sa app at piliin ang Ibalik ang account ko, o gamitin ang Ibalik ang account mo sa ibaba.',
      step3Title: 'Pagkalipas ng 30 araw',
      step3: 'Buburahin nang tuluyan ang sign-in at profile mo (pangalan, email, mobile number, kaarawan, kasarian, wika at huling lokasyon), ang mga alerto mo at anumang litrato ng National ID.',
      step4Title: 'Ano ang mananatili',
      step4: 'Mananatili sa talaan ng mga insidente ng barangay ang mga report na ipinadala mo, pero wala na ang pangalan mo.',
      staffNote: 'Ang mga staff account (coordinator at responder) ay binubura ng administrator ng organisasyon nila.',
      deleteHeading: 'Burahin ang account ko',
      email: 'Email',
      password: 'Password',
      show: 'Ipakita',
      hide: 'Itago',
      tick: 'Naiintindihan ko na ifi-freeze ngayon ang account ko at buburahin nang tuluyan pagkalipas ng 30 araw kung hindi ko ito ibabalik.',
      deleteBtn: 'Burahin ang account ko',
      working: 'Sandali…',
      needBoth: 'Ilagay ang email at password ng RepLiT account mo.',
      needTick: 'I-tick ang box para kumpirmahin.',
      deleted: 'Naka-freeze na ang account mo. Buburahin ito nang tuluyan sa {date}. Para manatili ito, ibalik ito bago ang araw na iyon.',
      restoreHeading: 'Nagbago ang isip mo? Ibalik ang account mo',
      restoreLede: 'Sa loob ng 30 araw mula nang hilingin mong burahin ito, babalik ang account mo kung paano ito dati.',
      restoreBtn: 'Ibalik ang account ko',
      restored: 'Naibalik na ang account mo. Puwede ka nang mag-sign in sa app gaya ng dati.',
      wrong: 'Mali ang email o password.',
      staff: 'Staff account ito. Ang administrator ng organisasyon mo ang nagbubura nito.',
      notScheduled: 'Hindi nakatakdang burahin ang account na ito. Puwede kang mag-sign in gaya ng dati.',
      unavailable: 'Hindi pa puwedeng magbura o magbalik ng account ngayon. Subukan ulit mamaya.',
      offline: 'Hindi maabot ang RepLiT. Tingnan ang internet connection mo at subukan ulit. Puwedeng umabot ng isang minuto bago ito magising.',
      generic: 'May nagkaproblema. Subukan ulit pagkalipas ng isang minuto.',
      home: 'RepLiT para sa mga residente',
      privacyLink: 'Privacy policy'
    }
  };

  var lang = 'en';
  try {
    var saved = window.localStorage.getItem('replit-lang');
    if (saved === 'en' || saved === 'tl') lang = saved;
    else if (/^(fil|tl)\b/i.test(navigator.language || '')) lang = 'tl';
  } catch (e) { /* no storage: English */ }

  function t(key, vars) {
    var s = (TEXT[lang] && TEXT[lang][key]) || TEXT.en[key] || key;
    if (vars) Object.keys(vars).forEach(function (k) { s = s.replace('{' + k + '}', vars[k]); });
    return s;
  }

  function applyLang() {
    document.documentElement.lang = lang === 'tl' ? 'fil' : 'en';
    document.querySelectorAll('[data-i18n]').forEach(function (el) {
      if (el.classList.contains('reveal')) {
        var input = el.parentNode.querySelector('input');
        el.textContent = input && input.type === 'text' ? t('hide') : t('show');
      } else {
        el.textContent = t(el.getAttribute('data-i18n'));
      }
    });
    document.querySelectorAll('[data-lang]').forEach(function (b) {
      b.setAttribute('aria-pressed', String(b.getAttribute('data-lang') === lang));
    });
    document.title = t('title');
  }

  document.querySelectorAll('[data-lang]').forEach(function (b) {
    b.addEventListener('click', function () {
      lang = b.getAttribute('data-lang');
      try { window.localStorage.setItem('replit-lang', lang); } catch (e) { /* fine */ }
      applyLang();
    });
  });

  document.querySelectorAll('.reveal').forEach(function (b) {
    b.addEventListener('click', function () {
      var input = b.parentNode.querySelector('input');
      input.type = input.type === 'password' ? 'text' : 'password';
      b.textContent = input.type === 'text' ? t('hide') : t('show');
    });
  });

  function dateOf(iso) {
    try {
      return new Date(iso).toLocaleDateString(lang === 'tl' ? 'fil-PH' : 'en-PH', {
        timeZone: 'Asia/Manila', day: 'numeric', month: 'long', year: 'numeric'
      });
    } catch (e) {
      return String(iso).slice(0, 10);
    }
  }

  function say(form, kind, text) {
    var box = form.querySelector('.message');
    box.className = 'message ' + kind;
    box.textContent = text;
    box.hidden = false;
  }

  function post(path, body) {
    var controller = typeof AbortController === 'function' ? new AbortController() : null;
    var timer = controller ? setTimeout(function () { controller.abort(); }, TIMEOUT_MS) : null;
    return fetch(API + path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: controller ? controller.signal : undefined
    }).then(function (resp) {
      return resp.json().catch(function () { return {}; }).then(function (data) {
        return { status: resp.status, data: data };
      });
    }).finally(function () { if (timer) clearTimeout(timer); });
  }

  function problem(res) {
    var code = res.data && res.data.error;
    if (code === 'wrong_password' || res.status === 401) return t('wrong');
    if (code === 'staff_account') return t('staff');
    if (code === 'not_scheduled') return t('notScheduled');
    if (code === 'deletion_unavailable') return t('unavailable');
    return t('generic');
  }

  function wire(form, path, needsTick, onDone) {
    var button = form.querySelector('button[type="submit"]');
    form.addEventListener('submit', function (event) {
      event.preventDefault();
      var email = form.email.value.trim();
      var password = form.password.value;
      if (!email || !password) return say(form, 'error', t('needBoth'));
      if (needsTick && !form.sure.checked) return say(form, 'error', t('needTick'));
      button.disabled = true;
      var label = button.textContent;
      button.textContent = t('working');
      post(path, { email: email, password: password }).then(function (res) {
        if (res.status === 200) {
          form.password.value = '';
          onDone(res.data);
        } else {
          say(form, 'error', problem(res));
        }
      }).catch(function () {
        say(form, 'error', t('offline'));
      }).finally(function () {
        button.disabled = false;
        button.textContent = label;
      });
    });
  }

  var deleteForm = document.getElementById('delete-form');
  var restoreForm = document.getElementById('restore-form');
  wire(deleteForm, '/auth/delete', true, function (data) {
    deleteForm.sure.checked = false;
    say(deleteForm, 'warn', t('deleted', { date: dateOf(data.delete_after) }));
  });
  wire(restoreForm, '/auth/restore', false, function () {
    say(restoreForm, 'ok', t('restored'));
  });

  applyLang();
})();
