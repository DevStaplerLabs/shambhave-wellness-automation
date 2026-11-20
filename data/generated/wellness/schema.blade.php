{{-- Paste in frontMaster.blade.php <head>, replacing the old JSON-LD blocks for this domain.
     Blade leaves @php blocks untouched, so "@context" is safe inside it (the old leak came from writing it
     directly in the template). --}}
@php
$schemaJson = <<<'JSON'
{
  "@context": "https://schema.org",
  "@graph": [
    {
      "@type": [
        "MedicalClinic",
        "LocalBusiness"
      ],
      "@id": "https://shambhavewellness.org/#clinic",
      "name": "Shambhave Wellness",
      "url": "https://shambhavewellness.org/",
      "telephone": "+919315311334",
      "email": "info@shambhavewellness.org",
      "image": "https://shambhavewellness.org/OGImage/shambhave-wellness.png",
      "logo": "https://shambhavewellness.org/assets/img/logo-color.svg",
      "address": {
        "@type": "PostalAddress",
        "streetAddress": "Orchid Petals, Sector 49",
        "addressLocality": "Gurugram",
        "addressRegion": "Haryana",
        "postalCode": "122018",
        "addressCountry": "IN"
      },
      "geo": {
        "@type": "GeoCoordinates",
        "latitude": 28.4187,
        "longitude": 77.0527
      },
      "openingHours": "Mo-Su 10:00-20:00",
      "knowsLanguage": [
        "English",
        "Hindi"
      ],
      "founder": {
        "@id": "https://shambhavewellness.org/#founder"
      },
      "employee": {
        "@id": "https://shambhavewellness.org/#founder"
      },
      "areaServed": [
        {
          "@type": "City",
          "name": "Gurugram"
        },
        {
          "@type": "Country",
          "name": "India"
        }
      ],
      "availableService": [
        {
          "@type": "MedicalTherapy",
          "name": "Psychotherapy"
        },
        {
          "@type": "MedicalTherapy",
          "name": "Clinical hypnotherapy"
        },
        {
          "@type": "MedicalTherapy",
          "name": "Narcissistic abuse recovery therapy"
        },
        {
          "@type": "MedicalTherapy",
          "name": "Marriage and relationship counselling"
        },
        {
          "@type": "MedicalTherapy",
          "name": "Trauma therapy"
        }
      ],
      "sameAs": [
        "https://www.youtube.com/@ShambhaveWellness",
        "https://www.instagram.com/shambhave_wellness/",
        "https://www.facebook.com/profile.php?id=61560963148382"
      ]
    },
    {
      "@type": "Person",
      "@id": "https://shambhavewellness.org/#founder",
      "name": "Dr. Amita Puri",
      "honorificPrefix": "Dr.",
      "jobTitle": "Clinical Psychologist",
      "url": "https://shambhavewellness.org/about-us",
      "image": "https://shambhavewellness.org/assets/img/international/dr_amita_puri_studio.webp",
      "worksFor": {
        "@id": "https://shambhavewellness.org/#clinic"
      },
      "knowsAbout": [
        "Narcissistic abuse recovery",
        "Trauma therapy",
        "Clinical hypnotherapy",
        "Psychotherapy",
        "Boundary work"
      ],
      "sameAs": [
        "https://www.amazon.in/Narcissism-Navigated-Harnessing-Personal-Growth-ebook/dp/B0DCT4P6YN",
        "https://walnutpublication.com/author/695014167"
      ]
    },
    {
      "@type": "WebSite",
      "@id": "https://shambhavewellness.org/#website",
      "url": "https://shambhavewellness.org/",
      "name": "Shambhave Wellness",
      "publisher": {
        "@id": "https://shambhavewellness.org/#clinic"
      },
      "inLanguage": "en-IN"
    }
  ]
}
JSON;
@endphp
<script type="application/ld+json">{!! $schemaJson !!}</script>
