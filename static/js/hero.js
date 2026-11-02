const heroImages = [
    "/static/image/hero.jpg",
    "/static/image/hero2.jpg",
    "/static/image/hero3.jpg",
    "/static/image/hero4.jpg"
];

let currentImage = Math.floor(Math.random() * heroImages.length);

const hero = document.querySelector(".hero");

function changeHeroImage() {

    hero.style.backgroundImage =
        `linear-gradient(
            90deg,
            rgba(5, 35, 65, 0.68),
            rgba(5, 35, 65, 0.08)
        ),
        url("${heroImages[currentImage]}")`;

    currentImage++;

    if (currentImage >= heroImages.length) {
        currentImage = 0;
    }
}

changeHeroImage();

setInterval(changeHeroImage, 4000);