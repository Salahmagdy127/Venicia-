/**
 * عامل الخدمة لتطبيق الميدان — Service worker.
 *
 * شغلته حاجة واحدة: إن التطبيق **يفتح** والموبايل مقطوع من الشبكة.
 * البيانات نفسها مش شغلته — دي في IndexedDB وبيديرها التطبيق.
 *
 * سياستان مختلفتان عن قصد:
 *
 *   الملفات (HTML/JS/CSS/أيقونات) → الكاش الأول.
 *      لأن الملف اللي معانا شغّال، وانتظار الشبكة عشان نتأكد إنه أحدث
 *      نسخة معناه شاشة بيضا لدقيقة في مكان مفيهوش إشارة. بنجيب
 *      التحديث في الخلفية للمرة الجاية.
 *
 *   طلبات الـ API → الشبكة وبس، من غير أي كاش.
 *      رد API قديم أسوأ بكتير من مفيش رد: التطبيق عارف يتصرّف لما
 *      الطلب يفشل (بيشتغل من نسختـه المحلية)، لكنه مش هيعرف إن الرد
 *      اللي جاله بتاع ساعتين فات.
 */

const CACHE = "venicia-field-v1";

//: أقل حاجة لازمة عشان الشاشة تفتح
const SHELL = ["/field", "/field-icon.svg", "/field.webmanifest"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      .then((cache) => cache.addAll(SHELL))
      .then(() => self.skipWaiting())
      .catch(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key))),
      )
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== location.origin) return;

  // الـ API مبيتخزّنش — رد قديم أخطر من غياب الرد
  if (url.pathname.startsWith("/api/")) return;

  // التنقّل: بنرجّع الغلاف من الكاش عشان التطبيق يفتح أوفلاين
  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        .then((response) => {
          const copy = response.clone();
          caches.open(CACHE).then((cache) => cache.put("/field", copy));
          return response;
        })
        .catch(() => caches.match("/field").then((hit) => hit || caches.match("/"))),
    );
    return;
  }

  event.respondWith(
    caches.match(request).then((hit) => {
      if (hit) {
        // موجود عندنا — بنرجّعه فوراً ونحدّثه في الخلفية بهدوء
        fetch(request)
          .then((response) => {
            if (response.ok) {
              const copy = response.clone();
              caches.open(CACHE).then((cache) => cache.put(request, copy));
            }
          })
          .catch(() => {});
        return hit;
      }
      return fetch(request)
        .then((response) => {
          if (response.ok && response.type === "basic") {
            const copy = response.clone();
            caches.open(CACHE).then((cache) => cache.put(request, copy));
          }
          return response;
        })
        .catch(() => caches.match("/field"));
    }),
  );
});
