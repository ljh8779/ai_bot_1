<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<title>Group Office</title>
<link href="?rev=" rel="shortcut icon"/>

	<style>
	body {margin:0}
	body, .go_wrap {min-width:600px}
	div.error_page {width:360px; margin:100px auto; padding:0; font-size:12px; font-family:돋움,dotum,AppleGothic,arial,Helvetica,sans-serif}
	
	div.view_content {background:url(/resources/images/bg_view.gif) repeat-x 0 -1px; padding:25px 20px; margin:0}
	div.error_page hgroup {position:relative; min-height:54px; display:block}
	div.error_page hgroup span.ic_error_page {display:inline-block; position:absolute; left:0; top:0; width:60px; background: url(/resources/images/ic_gnb.png) no-repeat -597px -720px; height:50px}
	div.error_page hgroup h2 {position:relative; display:inline-block; margin:10px 0 0 60px; font-size:18px; font-family:나눔고딕,맑은 고딕,돋움,nanumgothic,malgun gothic, dotum,AppleGothic,Helvetica,sans-serif}
	div.error_page .desc {display:block; font:12px/1.4 dotum; text-align:left; margin:10px 0 0 5px; color:#999; padding:0}
	
	.btn_major_s {display:inline-block; cursor:pointer; padding: 4px 8px 3px; color:#fff; font-weight:bold; font-size:12px; line-height:18px; border-radius:2px; background:#2197a3; border:1px solid #1e8d98}
	.btn_major_s:hover {background-color:#1c8691; border-color:#18808a}
	div.error_page a.btn_major_s {margin-left:120px; margin-top:20px}
	
	</style>
    <script type="text/javascript" src="/resources/js/vendors/jquery/jquery.js"></script>
<!--[if IE]>
<script src="http://html5shiv.googlecode.com/svn/trunk/html5.js"></script>
<![endif]-->
</head>
<body  class="full_page go_full_screen">

		<div class="view_content">
			<div class="error_page">
				<hgroup>
					<span class="ic_data_type ic_error_page"></span>
					<h2>Error</h2>
				</hgroup>
				<a class="btn_major_s" onclick="javascript:history.go(-1);" style="cursor: pointer; display: none;">
					<span class="txt">Back</span>
				</a>
			</div>	
		</div>	
		<script>
	        window.onload = function(){
	            if(history.length > 1){
	                $(".btn_major_s").show();
	            }
	        };
		</script>
		
</body>
</html>