<?php
// Shortlisted Educators Page
?>
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Shortlisted Educators</title>

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
.logo{
    font-weight:700;
    color:#2563eb;
}
.header-actions{
    display:flex;
    align-items:center;
    gap:14px;
    font-size:14px;
}
.signin{
    padding:6px 12px;
    border-radius:6px;
    border:1px solid #0f172a;
    background:#0f172a;
    color:#fff;
    font-size:13px;
    cursor:pointer;
}

/* ===== PAGE ===== */
.container{
    max-width:1200px;
    margin:28px auto;
    padding:0 24px;
}
.page-title{
    font-size:22px;
    font-weight:600;
    margin-bottom:20px;
}

/* ===== EDUCATOR CARD ===== */
.educator-card{
    background:#fff;
    border:1px solid #e5e7eb;
    border-radius:16px;
    padding:20px;
    box-shadow:0 4px 14px rgba(0,0,0,0.04);
}
.edu-head{
    display:flex;
    justify-content:space-between;
    align-items:flex-start;
}
.edu-info{
    display:flex;
    gap:16px;
}
.edu-info img{
    width:64px;
    height:64px;
    border-radius:50%;
    object-fit:cover;
}
.edu-info h3{
    font-size:16px;
}
.edu-info small{
    display:block;
    font-size:13px;
    color:#64748b;
    margin-top:4px;
}
.delete{
    cursor:pointer;
}

/* ===== DETAILS GRID ===== */
.edu-details{
    margin-top:18px;
    display:grid;
    grid-template-columns:repeat(4,1fr);
    gap:16px;
    font-size:14px;
}
.detail small{
    display:block;
    font-size:12px;
    color:#64748b;
    margin-bottom:4px;
}

/* ===== ACTIONS ===== */
.edu-actions{
    margin-top:18px;
    display:flex;
    gap:12px;
}
.book-btn{
    flex:1;
    padding:12px;
    background:#000;
    color:#fff;
    border:none;
    border-radius:10px;
    font-size:14px;
    cursor:pointer;
}
.profile-btn{
    flex:1;
    padding:12px;
    background:#fff;
    border:1px solid #e5e7eb;
    border-radius:10px;
    font-size:14px;
    cursor:pointer;
}

/* ===== BOTTOM CTA ===== */
.bottom-cta{
    margin:40px 0;
    text-align:center;
    font-size:14px;
}
.bottom-cta button{
    margin-top:10px;
    padding:10px 16px;
    border-radius:8px;
    border:1px solid #e5e7eb;
    background:#f1f5f9;
    cursor:pointer;
}

/* ===== FOOTER ===== */
.footer{
    background:#0f172a;
    color:#cbd5f5;
    padding:40px 24px 20px;
}
.footer-inner{
    max-width:1200px;
    margin:auto;
    display:grid;
    grid-template-columns:2fr 1fr 1fr 1fr;
    gap:24px;
}
.footer h4{
    color:#fff;
    margin-bottom:12px;
}
.footer ul{
    list-style:none;
}
.footer li{
    margin-bottom:8px;
    font-size:13px;
}
.footer-bottom{
    text-align:center;
    margin-top:30px;
    font-size:12px;
    color:#94a3b8;
    border-top:1px solid #1e293b;
    padding-top:14px;
}
</style>
</head>

<body>

<!-- HEADER -->
<div class="header">
    <div class="header-inner">
        <div class="logo">LOGO</div>
        <div class="header-actions">
            <span>Shortlisted</span>
            <button class="signin">Sign In</button>
        </div>
    </div>
</div>

<!-- PAGE -->
<div class="container">

    <div class="page-title">Shortlisted Educators (1)</div>

    <!-- EDUCATOR CARD -->
    <div class="educator-card">

        <div class="edu-head">
            <div class="edu-info">
                <img src="assets/images/doctor.jpg">
                <div>
                    <h3>Dr. Sarah Johnson</h3>
                    <small>Pediatrics</small>
                </div>
            </div>
            <img src="assets/images/delete.webp" class="delete" width="18">
        </div>

        <div class="edu-details">
            <div class="detail">
                <small>Next Available</small>
                <strong>Today, 2:00 PM</strong>
            </div>

            <div class="detail">
                <small>Session Fee</small>
                <strong>$150/hour</strong>
            </div>

            <div class="detail">
                <small>Languages</small>
                <strong>English, Hindi</strong>
            </div>

            <div class="detail">
                <small>Location</small>
                <strong>Virtual</strong>
            </div>
        </div>

        <div class="edu-actions">
            <button class="book-btn">Book Session</button>
            <button class="profile-btn">View Full Profile</button>
        </div>

    </div>

    <!-- BOTTOM CTA -->
    <div class="bottom-cta">
        <p>Looking for more educators?</p>
        <button>Browse All Educators</button>
    </div>

</div>

<!-- FOOTER -->
<div class="footer">
    <div class="footer-inner">
        <div>
            <strong>LOGO</strong>
            <p style="margin-top:10px;font-size:13px">
                Connecting educators and learners worldwide.
            </p>
        </div>

        <div>
            <h4>Company</h4>
            <ul>
                <li>About</li>
                <li>Careers</li>
                <li>Contact</li>
            </ul>
        </div>

        <div>
            <h4>Resources</h4>
            <ul>
                <li>Blog</li>
                <li>Help Center</li>
                <li>Terms</li>
            </ul>
        </div>

        <div>
            <h4>Follow Us</h4>
            <ul>
                <li>Twitter</li>
                <li>LinkedIn</li>
                <li>Facebook</li>
            </ul>
        </div>
    </div>

    <div class="footer-bottom">
        © 2024 All rights reserved.
    </div>
</div>

</body>
</html>
