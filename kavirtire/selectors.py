"""Central selector registry. Semantic fallbacks, NOT verified live selectors.

See README's provenance list. Do not create a root selectors.py: asyncio uses
the stdlib module of that name. Prefer adding a verified stable attribute here.
"""
LOGIN = ('ورود به حساب', 'ورود', 'ورود به سامانه')
LOGIN_NEXT = ('ارسال کد', 'ارسال کد تایید', 'دریافت کد', 'ادامه', 'تایید')
OTP_SUBMIT = ('ثبت', 'تایید', 'تأیید', 'ورود', 'تایید کد')
NATIONAL_ID_LABELS = ('کد ملی', 'کدملی')
NATIONAL_ID_CSS = ('input[name="n_code"]', 'input[autocomplete="username"]', 'input[name="nationalId"]',
                   'input[name="nationalCode"]')
LOGIN_ID_SUBMIT = ('ورود',)  # verified: /esale/login button[type=submit]
LOGIN_TERMS_CSS = '#confirm'  # verified: /esale checkbox; labelled acceptance text
LOGIN_TERMS_LABEL = 'شرایط فوق را به صورت کامل مطالعه کرده ام'
OTP_LABELS = ('کد تایید', 'کد تأیید', 'کد یکبار مصرف')
OTP_CSS = ('#code-verification', 'input[autocomplete="one-time-code"]', 'input[name="otp"]')
OTP_VALUE_PATTERN = r'(?:[0-9]{4,8}|[A-Za-z0-9]{8})'
OTP_SPLIT = 'input[maxlength="1"][inputmode="numeric"]'
AUTH_REJECTION = ('کد تایید نامعتبر', 'کد وارد شده صحیح نیست', 'کد منقضی',
                  'رمز اشتباه', 'کد ملی نامعتبر', 'کد ملی صحیح نیست')
PROFILE_SIGNALS = ('خروج از حساب', 'خروج', 'پروفایل', 'حساب کاربری')
SHOP = ('خرید', 'خرید تایر', 'خرید اینترنتی')
TERMS = ('قوانین', 'شرایط', 'می پذیرم', 'موافقم')
REFRESH = ('به روز رسانی موجودی', 'بروزرسانی موجودی', 'به روزرسانی موجودی',
           'بروز رسانی موجودی', 'تازه سازی موجودی')
PRODUCT_CONTAINERS = ('tr', '[role="row"]', 'article', '[role="listitem"]',
                      '[data-product-id]', '.product', '.product-card', '.product-item', '.card')
PRODUCT_LIST = ('.products', '[role="table"]', 'table', '[role="list"]', '[data-product-list]')
SELECT_PRODUCT = ('انتخاب', 'خرید', 'انتخاب محصول', 'افزودن به سبد خرید')
SAFE_SELECTION = ('انتخاب', 'انتخاب محصول', 'افزودن به سبد خرید')
OUT_OF_STOCK = ('ناموجود', 'اتمام موجودی', 'موجود نیست', 'موجودی صفر')
IN_STOCK = ('موجود', 'قابل خرید')
STOCK_LABELS = ('موجودی', 'تعداد موجود')
QUANTITY_LABELS = ('تعداد', 'تعداد حلقه', 'تعداد تایر')
QUANTITY_CSS = ('select[name="quantity"]', 'input[name="quantity"]',
                'input[type="number"]', '[role="spinbutton"]')
QUANTITY_DISPLAY = ('[data-quantity]', '[role="status"][aria-label*="تعداد"]', '.quantity-value')
PLUS = ('افزایش تعداد', 'افزایش', '+')
MINUS = ('کاهش تعداد', 'کاهش', '−', '-')
CHECKOUT_NEXT = ('ثبت سفارش', 'ادامه خرید', 'تکمیل سفارش', 'تایید سفارش',
                 'پرداخت', 'پرداخت آنلاین', 'اتصال به درگاه', 'ورود به درگاه')
ORDER_CONTAINERS = ('[data-order-item]', '[role="row"]', 'tr', 'article',
                    '[role="listitem"]', '.cart-item', '.order-item', '[data-order-summary]')
ORDER_REGIONS = ('[data-order-summary]', '[data-cart]', '[aria-label="خلاصه سفارش"]',
                 '[aria-label="سبد خرید"]', '.order-summary', '.shopping-cart')
ACTION_PHASES = {
    'ادامه خرید': 'continue',
    'ثبت سفارش': 'create_order', 'تکمیل سفارش': 'create_order', 'تایید سفارش': 'create_order',
    'پرداخت': 'payment', 'پرداخت آنلاین': 'payment', 'اتصال به درگاه': 'payment', 'ورود به درگاه': 'payment',
}
LOADING = '[role="progressbar"]:visible, [aria-busy="true"]:visible, .loading:visible, .spinner:visible'
PROTECTION_WIDGETS = ('iframe[src*="recaptcha"]:visible:not(.grecaptcha-badge iframe)', 'iframe[src*="hcaptcha"]:visible',
                      'iframe[src*="challenges.cloudflare.com"]:visible',
                      '[data-sitekey]:visible', 'input[name*="captcha" i]:visible',
                      'img[alt*="کپچا"]:visible')
PROTECTION_TEXT = ('تعداد درخواست بیش از حد', 'تعداد درخواست ها بیش از حد مجاز',
                   'در صف انتظار', 'نوبت شما', 'Too Many Requests',
                   'Verify you are human', 'Checking your browser', 'Access denied',
                   'کد امنیتی را وارد کنید')
QUANTITY_LIMIT = ('حداکثر تعداد', 'سقف مجاز خرید', 'محدودیت تعداد', 'بیش از حد مجاز')
PURCHASE_LIMIT_PATTERN = r'(?:امکان|حداکثر|سقف خرید)\s*(\d+)\s*حلقه\s*(?:تایر)?\s*(?:در|برای)'
TIRE_SIZE_PATTERN = r'(?<![0-9])\d{3}\s*/\s*\d{2}\s*[rR]\s*\d{2}(?![0-9])'
IS_QUANTITY_CONTROL_JS = """el => ['INPUT','SELECT','TEXTAREA'].includes(el.tagName)
  || el.getAttribute('role') === 'spinbutton'"""
SENSITIVE_FIELDS = 'input, textarea, select, [contenteditable="true"]'

# These scripts only observe UI changes; no hidden requests or security changes.
WATCH_REFRESH_JS = """() => {
  window.__kavirRefreshObserver?.disconnect();
  window.__kavirRefreshChanged = false;
  const root = document.body;
  window.__kavirRefreshObserver = new MutationObserver(() => {
    window.__kavirRefreshChanged = true;
  });
  window.__kavirRefreshObserver.observe(root, {subtree:true, childList:true,
    characterData:true, attributes:true});
}"""
WAIT_REFRESH_JS = '() => window.__kavirRefreshChanged === true'
WATCH_INVENTORY_JS = """(root) => {
  window.__kavirRefreshObserver?.disconnect();
  window.__kavirRefreshChanged = false;
  const parent = root.parentElement || root;
  window.__kavirRefreshObserver = new MutationObserver(records => {
    if (records.some(r => (root.contains(r.target) &&
      (r.type !== 'attributes' || ['hidden','disabled','aria-disabled','aria-hidden','data-stock'].includes(r.attributeName))) ||
      [...r.removedNodes, ...r.addedNodes].some(n => n === root))) {
      window.__kavirRefreshChanged = true;
    }
  });
  window.__kavirRefreshObserver.observe(parent, {subtree:true, childList:true,
    characterData:true, attributes:true});
}"""
QUANTITY_TEXT_JS = """(el) => el.value ?? el.getAttribute('data-quantity') ?? el.textContent"""
WATCH_CHECKOUT_JS = """(oldText) => {
  window.__kavirCheckoutObserver?.disconnect();
  window.__kavirCheckoutObserver = new MutationObserver(() => {
    if (document.body.innerText !== oldText) {
      window.__kavirCheckoutObserver.disconnect();
      window.__kavir_checkout_changed();
    }
  });
  window.__kavirCheckoutObserver.observe(document.body, {subtree:true,
    childList:true,characterData:true,attributes:true});
}"""
WAIT_QUANTITY_JS = """(root, args) => new Promise((resolve, reject) => {
  const normalize = s => (s || '').replace(/[۰-۹]/g, d=>String(d.charCodeAt(0)-0x6f0))
    .replace(/[٠-٩]/g, d=>String(d.charCodeAt(0)-0x660));
  const read = () => {
    const el = root.querySelector(args.selectors.join(','));
    return el ? (el.value ?? el.getAttribute('data-quantity') ?? el.textContent) : '';
  };
  const changed = () => { const m=normalize(read()).match(/\\d+/g);
    return m && m.length === 1 && Number(m[0]) !== args.before; };
  if(changed()) return resolve();
  const observer = new MutationObserver(() => {if(changed()) finish();});
  const onInput=()=>{if(changed()) finish();};
  const cleanup=()=>{observer.disconnect(); root.removeEventListener('input',onInput,true);
    root.removeEventListener('change',onInput,true); clearTimeout(timer);};
  const finish=()=>{cleanup();resolve();};
  observer.observe(root,{subtree:true,attributes:true,childList:true,characterData:true});
  root.addEventListener('input',onInput,true); root.addEventListener('change',onInput,true);
  const timer=setTimeout(()=>{cleanup();reject(new Error('Quantity update timeout'));},args.timeout);
})"""
SANITIZE_HTML_JS = """() => {
  const root = document.documentElement.cloneNode(true);
  root.querySelectorAll('script,style,iframe,object,embed,meta,link,noscript,template').forEach(e=>e.remove());
  root.querySelectorAll('*').forEach(el => {
    for (const a of [...el.attributes]) {
      if (!['role','type','class'].includes(a.name)) el.removeAttribute(a.name);
    }
    if (['INPUT','TEXTAREA','SELECT'].includes(el.tagName)) {
      el.textContent=''; el.setAttribute('value','[REDACTED]');
    }
  });
  const walk = document.createTreeWalker(root, NodeFilter.SHOW_COMMENT);
  const comments=[]; while(walk.nextNode()) comments.push(walk.currentNode);
  comments.forEach(n=>n.remove());
  return '<!doctype html>\\n' + root.outerHTML;
}"""
