{{-- Paste in frontMaster.blade.php <head>, replacing the old JSON-LD blocks for this domain.
     Blade leaves @php blocks untouched, so "@context" is safe inside it (the old leak came from writing it
     directly in the template). --}}
@php
$schemaJson = <<<'JSON'
{
  "@context": "https://schema.org",
  "@graph": [
    {
      "@type": "NGO",
      "@id": "https://foundation.shambhavewellness.org/#organization",
      "name": "Shambhave Wellness Foundation",
      "url": "https://foundation.shambhavewellness.org/",
      "description": "Non-profit arm of Shambhave Wellness running community mental health programmes, subsidised therapy and volunteering in India.",
      "email": "info@shambhavewellness.org",
      "telephone": "+919315311334",
      "parentOrganization": {
        "@id": "https://shambhavewellness.org/#clinic"
      },
      "founder": {
        "@id": "https://shambhavewellness.org/#founder"
      },
      "areaServed": {
        "@type": "Country",
        "name": "India"
      }
    },
    {
      "@type": "WebSite",
      "@id": "https://foundation.shambhavewellness.org/#website",
      "url": "https://foundation.shambhavewellness.org/",
      "name": "Shambhave Wellness Foundation",
      "publisher": {
        "@id": "https://foundation.shambhavewellness.org/#organization"
      },
      "inLanguage": "en-IN"
    }
  ]
}
JSON;
@endphp
<script type="application/ld+json">{!! $schemaJson !!}</script>
