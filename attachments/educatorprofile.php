<?php
// Educator Profile Page
?>
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Educator Profile</title>

<style>
*{margin:0;padding:0;box-sizing:border-box}
body{
    font-family:Inter, system-ui, sans-serif;
    background:#f8fafc;
    color:#0f172a;
}

/* ===== HEADER ===== */
.header{
    background:#fff;
    border-bottom:1px solid #e5e7eb;
}
.header-inner{
    max-width:1400px;
    margin:auto;
    padding:14px 24px;
    display:flex;
    justify-content:space-between;
    align-items:center;
}
.logo{font-weight:700;color:#2563eb}
.signin{
    padding:6px 12px;
    border-radius:6px;
    background:#0f172a;
    color:#fff;
    border:none;
    font-size:13px;
}

/* ===== PAGE ===== */
.container{
    max-width:1400px;
    margin:24px auto;
    padding:0 24px;
}
.grid{
    display:grid;
    grid-template-columns:1.2fr 1fr;
    gap:24px;
}

/* ===== CARD ===== */
.card{
    background:#fff;
    border:1px solid #e5e7eb;
    border-radius:16px;
    padding:20px;
}

/* ===== PROFILE ===== */
.profile-head{
    display:flex;
    gap:16px;
    align-items:center;
    margin-bottom:16px;
}
.profile-head img{
    width:72px;
    height:72px;
    border-radius:50%;
    object-fit:cover;
}
.profile-head h2{
    font-size:18px;
}
.profile-head small{
    display:block;
    font-size:13px;
    color:#64748b;
}
.verified{
    display:inline-flex;
    align-items:center;
    gap:6px;
    background:#dcfce7;
    color:#166534;
    padding:4px 10px;
    border-radius:20px;
    font-size:12px;
    margin-left:8px;
}

/* ===== SECTIONS ===== */
.section{
    margin-top:18px;
}
.section h4{
    margin-bottom:8px;
}
.section p{
    font-size:14px;
    color:#334155;
    line-height:1.6;
}

/* ===== TAGS ===== */
.tags span{
    display:inline-block;
    margin:6px 6px 0 0;
    padding:6px 10px;
    background:#eef2ff;
    color:#4338ca;
    border-radius:20px;
    font-size:12px;
}

/* ===== BOOKING ===== */
.book-head{
    display:flex;
    justify-content:space-between;
    align-items:center;
    margin-bottom:10px;
}
.calendar{
    margin-top:10px;
}
.days{
    display:grid;
    grid-template-columns:repeat(7,1fr);
    text-align:center;
    font-size:12px;
    color:#64748b;
}
.dates{
    display:grid;
    grid-template-columns:repeat(7,1fr);
    gap:6px;
    margin-top:8px;
}
.date{
    padding:8px;
    border-radius:8px;
    border:1px solid #e5e7eb;
    font-size:13px;
    text-align:center;
}

/* ===== TIME SLOTS ===== */
.slots{
    margin-top:14px;
    display:grid;
    grid-template-columns:repeat(3,1fr);
    gap:10px;
}
.slot{
    padding:8px;
    border:1px solid #e5e7eb;
    border-radius:8px;
    text-align:center;
    font-size:13px;
    cursor:pointer;
}

/* ===== DURATION ===== */
.duration{
    margin-top:14px;
    display:grid;
    grid-template-columns:repeat(3,1fr);
    gap:10px;
}
.duration div{
    padding:8px;
    border-radius:8px;
    border:1px solid #e5e7eb;
    text-align:center;
    font-size:13px;
}
.duration .active{
    background:#000;
    color:#fff;
    border:none;
}

/* ===== PRICE ===== */
.price{
    margin-top:16px;
    display:flex;
    justify-content:space-between;
    align-items:center;
    font-size:15px;
    font-weight:600;
}

/* ===== DISCOUNT ===== */
.discount{
    margin-top:12px;
    background:#dcfce7;
    color:#166534;
    padding:10px;
    border-radius:10px;
    font-size:13px;
}

/* ===== CTA ===== */
.book-btn{
    margin-top:16px;
    width:100%;
    padding:12px;
    background:#000;
    color:#fff;
    border:none;
    border-radius:10px;
    font-size:14px;
}
.note{
    margin-top:8px;
    font-size:11px;
    color:#64748b;
    text-align:center;
}
.footer-note{
    margin-top:30px;
    text-align:center;
    font-size:12px;
    color:#64748b;
}
</style>
</head>

<body>

<!-- HEADER -->
<div class="header">
    <div class="header-inner">
        <div class="logo">LOGO</div>
        <button class="signin">Sign In</button>
    </div>
</div>

<div class="container">
<div class="grid">

<!-- LEFT PROFILE -->
<div class="card">

    <div class="profile-head">
        <img src="assets/images/doctor.jpg">
        <div>
            <h2>
                Dr. Sarah Anderson, MD
                <span class="verified">✔ Verified</span>
            </h2>
            <small>Medical Education Specialist</small>
        </div>
    </div>

    <div class="section">
        <h4>About Me</h4>
        <p>
            With over 12 years of clinical and teaching experience, I specialize in
            medical education, particularly in anatomy, physiology, and clinical skills.
            I hold an MD from Johns Hopkins University and have helped hundreds of
            medical students and residents excel in their medical education journey.
        </p>
    </div>

    <div class="section">
        <h4>Specializations</h4>
        <div class="tags">
            <span>Clinical Skills</span>
            <span>Anatomy</span>
            <span>Physiology</span>
            <span>USMLE Prep</span>
        </div>
    </div>

</div>

<!-- RIGHT BOOKING -->
<div class="card">

    <div class="book-head">
        <strong>Book a Session</strong>
        <small>Synced with Google Calendar</small>
    </div>

    <div class="calendar">
        <div class="days">
            <div>Sat</div><div>Sun</div><div>Mon</div>
            <div>Tue</div><div>Wed</div><div>Thu</div><div>Fri</div>
        </div>
        <div class="dates">
            <div class="date">28</div><div class="date">29</div><div class="date">30</div>
            <div class="date">1</div><div class="date">2</div><div class="date">3</div><div class="date">4</div>
        </div>
    </div>

    <div class="section">
        <h4>Available Time Slots</h4>
        <div class="slots">
            <div class="slot">9:00 AM</div>
            <div class="slot">10:30 AM</div>
            <div class="slot">2:00 PM</div>
            <div class="slot">3:30 PM</div>
            <div class="slot">5:00 PM</div>
            <div class="slot">6:30 PM</div>
        </div>
    </div>

    <div class="section">
        <h4>Session Duration</h4>
        <div class="duration">
            <div>30 mins</div>
            <div class="active">45 mins</div>
            <div>60 mins</div>
        </div>
    </div>

    <div class="price">
        <span>Session Fee</span>
        <span>₹2500</span>
    </div>

    <div class="discount">
        🎉 New Student Discount <br>
        15% off your first session with code <strong>NEWSTUDENT15</strong>
    </div>

    <button class="book-btn">Book Session with Google Calendar</button>

    <div class="note">
        Sessions will be automatically added to your Google Calendar.
        Payment will be processed securely via Razorpay.
        Free cancellation up to 24 hours before the session.
    </div>

</div>

</div>

<div class="footer-note">
    © 2024 MedEd Platform. All rights reserved. Powered by Google Calendar & Razorpay.
</div>

</div>

</body>
</html>
