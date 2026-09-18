(function () {
  var box = document.getElementById("chart-lightbox");
  if (!box) return;

  var stageInner = document.getElementById("chart-lightbox-inner");
  var img = document.getElementById("chart-lightbox-img");
  var btnClose = box.querySelector(".chart-lightbox-close");
  var btnRotate = document.getElementById("chart-lightbox-rotate");
  var rotation = 0;

  function applyRotation() {
    if (!img) return;
    img.style.transform = "rotate(" + rotation + "deg)";
    if (rotation % 180 === 90) {
      img.style.maxWidth = "min(92vh, 92vw)";
      img.style.maxHeight = "min(92vw, 92vh)";
    } else {
      img.style.maxWidth = "min(96vw, 96vh)";
      img.style.maxHeight = "min(96vh, 96vw)";
    }
  }

  function openLightbox(src, alt) {
    rotation = 0;
    img.src = src;
    img.alt = alt || "BTCUSDT scenario chart";
    img.style.transform = "rotate(0deg)";
    img.style.maxWidth = "";
    img.style.maxHeight = "";
    box.hidden = false;
    box.setAttribute("aria-hidden", "false");
    document.body.classList.add("chart-lightbox-open");
    applyRotation();
  }

  function closeLightbox() {
    box.hidden = true;
    box.setAttribute("aria-hidden", "true");
    document.body.classList.remove("chart-lightbox-open");
    img.removeAttribute("src");
  }

  document.addEventListener("click", function (e) {
    var t = e.target;
    if (!(t instanceof Element)) return;
    var preview = t.closest(".chart-preview");
    if (preview && preview instanceof HTMLImageElement) {
      e.preventDefault();
      openLightbox(preview.currentSrc || preview.src, preview.alt);
    }
  });

  if (btnClose) {
    btnClose.addEventListener("click", closeLightbox);
  }

  box.addEventListener("click", function (e) {
    if (e.target === box) closeLightbox();
  });

  if (btnRotate) {
    btnRotate.addEventListener("click", function (e) {
      e.stopPropagation();
      rotation = (rotation + 90) % 360;
      applyRotation();
    });
  }

  document.addEventListener("keydown", function (e) {
    if (box.hidden) return;
    if (e.key === "Escape") closeLightbox();
  });
})();
