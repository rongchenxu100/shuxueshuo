function setupInteractiveDemo() {
  const board = document.querySelector("[data-geo-board]");
  const pointSlider = document.querySelector("[data-control='point']");
  const rotationSlider = document.querySelector("[data-control='rotation']");
  const steps = Array.from(document.querySelectorAll("[data-step-card]"));

  if (!board || !pointSlider || !rotationSlider || !steps.length) {
    return;
  }

  function updateBoard() {
    const pointValue = Number(pointSlider.value);
    const rotationValue = Number(rotationSlider.value);

    board.style.setProperty("--point-left", `${pointValue}%`);
    board.style.setProperty("--shape-rotation", `${rotationValue}deg`);

    const activeStep = rotationValue > 32 ? 2 : pointValue > 55 ? 1 : 0;
    steps.forEach((card, index) => {
      card.classList.toggle("active-step", index === activeStep);
    });
  }

  pointSlider.addEventListener("input", updateBoard);
  rotationSlider.addEventListener("input", updateBoard);
  updateBoard();
}

setupInteractiveDemo();
