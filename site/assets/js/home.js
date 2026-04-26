(() => {
  const backToTop = document.querySelector(".back-to-top");
  if (!backToTop) {
    return;
  }

  const showAt = 520;
  const toggleVisibility = () => {
    const shouldShow = window.scrollY > showAt;
    backToTop.classList.toggle("is-visible", shouldShow);
  };

  window.addEventListener("scroll", toggleVisibility, { passive: true });
  toggleVisibility();

  backToTop.addEventListener("click", () => {
    window.scrollTo({ top: 0, behavior: "smooth" });
  });
})();
